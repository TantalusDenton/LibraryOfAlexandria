"""ARM templates using managed identities, private PostgreSQL, and Consumption compute."""

from datetime import date
from hashlib import sha256

APP_API = "2025-01-01"


def template(resources, parameters=None, outputs=None):
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
        "contentVersion": "1.0.0.0",
        "parameters": parameters or {},
        "resources": resources,
        "outputs": outputs or {},
    }


def rid(kind, *names):
    return "[resourceId(" + ", ".join(repr(v) for v in (kind, *names)) + ")]"


def ref(kind, name, api, property_name):
    return f"[reference(resourceId('{kind}', '{name}'), '{api}').{property_name}]"


def names(suffix):
    return {
        key: f"loa{suffix}{tail}"
        for key, tail in {
            "storage": "st",
            "registry": "acr",
            "vault": "kv",
            "postgres": "db",
            "identity": "id",
            "network": "net",
            "environment": "env",
            "logs": "logs",
            "app": "studio",
            "worker": "worker",
            "recovery": "recover",
            "migration": "migrate",
        }.items()
    }


def foundation(n, location, owner_email, database_sku="Standard_B2s"):
    resources = []

    def add(resource_type, name, api, properties=None, **extra):
        item = {"type": resource_type, "name": name, "apiVersion": api, **extra}
        if properties is not None:
            item["properties"] = properties
        resources.append(item)
        return rid(resource_type, *name.split("/"))

    identity = add(
        "Microsoft.ManagedIdentity/userAssignedIdentities",
        n["identity"],
        "2023-01-31",
        location=location,
    )
    network = add(
        "Microsoft.Network/virtualNetworks",
        n["network"],
        "2024-05-01",
        {
            "addressSpace": {"addressPrefixes": ["10.42.0.0/16"]},
            "subnets": [
                {
                    "name": "containers",
                    "properties": {
                        "addressPrefix": "10.42.0.0/24",
                        "defaultOutboundAccess": True,
                        "delegations": [
                            {
                                "name": "containers",
                                "properties": {
                                    "serviceName": "Microsoft.App/environments"
                                },
                            }
                        ],
                    },
                },
                {
                    "name": "postgres",
                    "properties": {
                        "addressPrefix": "10.42.1.0/27",
                        "delegations": [
                            {
                                "name": "postgres",
                                "properties": {
                                    "serviceName": "Microsoft.DBforPostgreSQL/flexibleServers"
                                },
                            }
                        ],
                    },
                },
            ],
        },
        location=location,
    )
    dns_name = f"{n['postgres']}.private.postgres.database.azure.com"
    dns = add(
        "Microsoft.Network/privateDnsZones",
        dns_name,
        "2020-06-01",
        {},
        location="global",
    )
    dns_link = add(
        "Microsoft.Network/privateDnsZones/virtualNetworkLinks",
        dns_name + "/studio",
        "2020-06-01",
        {"virtualNetwork": {"id": network}, "registrationEnabled": False},
        location="global",
        dependsOn=[dns, network],
    )
    storage = add(
        "Microsoft.Storage/storageAccounts",
        n["storage"],
        "2023-05-01",
        {
            "supportsHttpsTrafficOnly": True,
            "minimumTlsVersion": "TLS1_2",
            "allowBlobPublicAccess": False,
            "allowSharedKeyAccess": False,
            "defaultToOAuthAuthentication": True,
        },
        location=location,
        kind="StorageV2",
        sku={"name": "Standard_LRS"},
    )
    blobs = add(
        "Microsoft.Storage/storageAccounts/blobServices",
        n["storage"] + "/default",
        "2023-05-01",
        {
            "isVersioningEnabled": True,
            "deleteRetentionPolicy": {"enabled": True, "days": 7},
            "containerDeleteRetentionPolicy": {"enabled": True, "days": 7},
        },
        dependsOn=[storage],
    )
    add(
        "Microsoft.Storage/storageAccounts/blobServices/containers",
        n["storage"] + "/default/objects",
        "2023-05-01",
        {"publicAccess": "None"},
        dependsOn=[blobs],
    )
    queues = add(
        "Microsoft.Storage/storageAccounts/queueServices",
        n["storage"] + "/default",
        "2023-05-01",
        {},
        dependsOn=[storage],
    )
    add(
        "Microsoft.Storage/storageAccounts/queueServices/queues",
        n["storage"] + "/default/generation",
        "2023-05-01",
        {},
        dependsOn=[queues],
    )
    registry = add(
        "Microsoft.ContainerRegistry/registries",
        n["registry"],
        "2023-07-01",
        {
            "adminUserEnabled": False,
            "anonymousPullEnabled": False,
        },
        location=location,
        sku={"name": "Basic"},
    )
    vault = add(
        "Microsoft.KeyVault/vaults",
        n["vault"],
        "2023-07-01",
        {
            "tenantId": "[subscription().tenantId]",
            "sku": {"family": "A", "name": "standard"},
            "enableRbacAuthorization": True,
            "enableSoftDelete": True,
            "softDeleteRetentionInDays": 7,
            "enablePurgeProtection": True,
            "accessPolicies": [],
        },
        location=location,
    )
    postgres = add(
        "Microsoft.DBforPostgreSQL/flexibleServers",
        n["postgres"],
        "2024-08-01",
        {
            "version": "16",
            "administratorLogin": "alexandria",
            "administratorLoginPassword": "[parameters('databasePassword')]",
            "storage": {"storageSizeGB": 32},
            "backup": {"backupRetentionDays": 7, "geoRedundantBackup": "Disabled"},
            "highAvailability": {"mode": "Disabled"},
            "network": {
                "delegatedSubnetResourceId": rid(
                    "Microsoft.Network/virtualNetworks/subnets",
                    n["network"],
                    "postgres",
                ),
                "privateDnsZoneArmResourceId": dns,
                "publicNetworkAccess": "Disabled",
            },
            "authConfig": {
                "activeDirectoryAuth": "Disabled",
                "passwordAuth": "Enabled",
            },
        },
        location=location,
        sku={"name": database_sku, "tier": "Burstable"},
        dependsOn=[network, dns_link],
    )
    add(
        "Microsoft.DBforPostgreSQL/flexibleServers/databases",
        n["postgres"] + "/alexandria",
        "2024-08-01",
        {"charset": "UTF8", "collation": "en_US.utf8"},
        dependsOn=[postgres],
    )
    host = f"reference(resourceId('Microsoft.DBforPostgreSQL/flexibleServers', '{n['postgres']}'), '2024-08-01').fullyQualifiedDomainName"
    values = {
        "database-url": f"[concat('postgresql+psycopg://alexandria:', parameters('databasePassword'), '@', {host}, '/alexandria?sslmode=verify-full&sslrootcert=/etc/ssl/certs/ca-certificates.crt')]",
        "checkpoint-url": f"[concat('postgresql://alexandria:', parameters('databasePassword'), '@', {host}, '/alexandria?sslmode=verify-full&sslrootcert=/etc/ssl/certs/ca-certificates.crt')]",
        "session-key": "[parameters('sessionKey')]",
        "owner-password": "[parameters('ownerPassword')]",
    }
    for key, value in values.items():
        add(
            "Microsoft.KeyVault/vaults/secrets",
            n["vault"] + "/" + key,
            "2023-07-01",
            {"value": value},
            dependsOn=[vault, postgres],
        )
    principal = ref(
        "Microsoft.ManagedIdentity/userAssignedIdentities",
        n["identity"],
        "2023-01-31",
        "principalId",
    )
    for scope, role in [
        (storage, "ba92f5b4-2d11-453d-a403-e96b0029c9fe"),  # Blob Data Contributor
        (storage, "974c5e8b-45b9-4653-ba55-5f855dd0fb88"),  # Queue Data Contributor
        (registry, "7f951dda-4ed3-4680-a7ca-43fe172d538d"),  # AcrPull
        (vault, "4633458b-17de-408a-b874-0445c86b69e6"),  # Key Vault Secrets User
    ]:
        add(
            "Microsoft.Authorization/roleAssignments",
            f"[guid({scope[1:-1]}, '{n['identity']}', '{role}')]",
            "2022-04-01",
            {
                "roleDefinitionId": f"[subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '{role}')]",
                "principalId": principal,
                "principalType": "ServicePrincipal",
            },
            scope=scope,
            dependsOn=[scope, identity],
        )
    logs = add(
        "Microsoft.OperationalInsights/workspaces",
        n["logs"],
        "2023-09-01",
        {
            "sku": {"name": "PerGB2018"},
            "retentionInDays": 30,
            "workspaceCapping": {"dailyQuotaGb": "[json('0.1')]"},
        },
        location=location,
    )
    add(
        "Microsoft.App/managedEnvironments",
        n["environment"],
        APP_API,
        {
            "workloadProfiles": [
                {"name": "Consumption", "workloadProfileType": "Consumption"}
            ],
            "vnetConfiguration": {
                "infrastructureSubnetId": rid(
                    "Microsoft.Network/virtualNetworks/subnets",
                    n["network"],
                    "containers",
                ),
                "internal": False,
            },
            "appLogsConfiguration": {
                "destination": "log-analytics",
                "logAnalyticsConfiguration": {
                    "customerId": ref(
                        "Microsoft.OperationalInsights/workspaces",
                        n["logs"],
                        "2023-09-01",
                        "customerId",
                    ),
                    "sharedKey": f"[listKeys(resourceId('Microsoft.OperationalInsights/workspaces', '{n['logs']}'), '2023-09-01').primarySharedKey]",
                },
            },
        },
        location=location,
        dependsOn=[network, logs],
    )
    today = date.today()
    add(
        "Microsoft.Consumption/budgets",
        "alexandria-monthly",
        "2023-05-01",
        {
            "category": "Cost",
            "amount": 75,
            "timeGrain": "Monthly",
            "timePeriod": {
                "startDate": f"{today:%Y-%m}-01T00:00:00Z",
                "endDate": f"{today.year + 2}-12-31T00:00:00Z",
            },
            "notifications": {
                f"actual-{amount}": {
                    "enabled": True,
                    "operator": "GreaterThanOrEqualTo",
                    "threshold": round(amount / 75 * 100),
                    "thresholdType": "Actual",
                    "contactEmails": [owner_email],
                }
                for amount in (50, 75, 100)
            },
        },
    )
    return template(
        resources,
        {
            key: {"type": "securestring"}
            for key in ("databasePassword", "sessionKey", "ownerPassword")
        },
    )


def runtime(n, location, owner_email, image_tag, phase="app", session_key_url=None):
    identity = rid("Microsoft.ManagedIdentity/userAssignedIdentities", n["identity"])
    secrets = [
        {
            "name": name,
            "keyVaultUrl": f"https://{n['vault']}.vault.azure.net/secrets/{name}",
            "identity": identity,
        }
        for name in ("database-url", "checkpoint-url", "session-key")
    ]
    if session_key_url:
        next(secret for secret in secrets if secret["name"] == "session-key")[
            "keyVaultUrl"
        ] = session_key_url
    env = [
        {"name": key, "value": value}
        for key, value in {
            "AI_MODE": "offline",
            "PRICING_CONFIRMED": "false",
            "DATA_DIR": "/app/data",
            "STORAGE_BACKEND": "azure",
            "AZURE_STORAGE_ACCOUNT_URL": f"https://{n['storage']}.blob.core.windows.net",
            "AZURE_BLOB_CONTAINER": "objects",
            "AZURE_QUEUE_URL": f"https://{n['storage']}.queue.core.windows.net/generation",
            "AZURE_CLIENT_ID": ref(
                "Microsoft.ManagedIdentity/userAssignedIdentities",
                n["identity"],
                "2023-01-31",
                "clientId",
            ),
            "SECURE_COOKIES": "true",
            "REGISTRATION_ENABLED": "false",
        }.items()
    ] + [
        {"name": key, "secretRef": secret}
        for key, secret in (
            ("DATABASE_URL", "database-url"),
            ("CHECKPOINT_URL", "checkpoint-url"),
            ("JWT_SECRET", "session-key"),
        )
    ]
    registry = {"server": f"{n['registry']}.azurecr.io", "identity": identity}

    def container(name, command=None, args=None):
        result = {
            "name": name,
            "image": f"{n['registry']}.azurecr.io/backend:{image_tag}",
            "env": list(env),
            "resources": {"cpu": 1, "memory": "2Gi"},
        }
        if command:
            result["command"] = command
        if args:
            result["args"] = args
        return result

    def job(key, config, spec):
        return {
            "type": "Microsoft.App/jobs",
            "apiVersion": APP_API,
            "name": n[key],
            "location": location,
            "identity": {
                "type": "UserAssigned",
                "userAssignedIdentities": {identity: {}},
            },
            "properties": {
                "environmentId": rid(
                    "Microsoft.App/managedEnvironments", n["environment"]
                ),
                "workloadProfileName": "Consumption",
                "configuration": {
                    "replicaTimeout": 21600,
                    "replicaRetryLimit": 0,
                    "secrets": list(secrets),
                    "registries": [registry],
                    **config,
                },
                "template": {"containers": [spec]},
            },
        }

    if phase == "migration":
        spec = container(
            "migrate",
            ["/bin/sh", "-c"],
            [
                ".venv/bin/alembic upgrade head && .venv/bin/python -m app.azure_bootstrap"
            ],
        )
        spec["env"] += [
            {"name": "OWNER_EMAIL", "value": owner_email},
            {"name": "OWNER_PASSWORD", "secretRef": "owner-password"},
        ]
        migration = job(
            "migration",
            {
                "triggerType": "Manual",
                "manualTriggerConfig": {"parallelism": 1, "replicaCompletionCount": 1},
            },
            spec,
        )
        migration["properties"]["configuration"]["secrets"].append(
            {
                "name": "owner-password",
                "keyVaultUrl": f"https://{n['vault']}.vault.azure.net/secrets/owner-password",
                "identity": identity,
            }
        )
        return template([migration])

    worker = job(
        "worker",
        {
            "triggerType": "Event",
            "eventTriggerConfig": {
                "parallelism": 1,
                "replicaCompletionCount": 1,
                "scale": {
                    "minExecutions": 0,
                    "maxExecutions": 2,
                    "pollingInterval": 30,
                    "rules": [
                        {
                            "name": "pending-work",
                            "type": "azure-queue",
                            "identity": identity,
                            "metadata": {
                                "queueName": "generation",
                                "accountName": n["storage"],
                                "queueLength": "1",
                                "queueLengthStrategy": "visibleonly",
                            },
                        }
                    ],
                },
            },
        },
        container("worker", [".venv/bin/python", "-m", "app.azure_worker"]),
    )
    recovery = job(
        "recovery",
        {
            "triggerType": "Schedule",
            "scheduleTriggerConfig": {
                "cronExpression": "*/5 * * * *",
                "parallelism": 1,
                "replicaCompletionCount": 1,
            },
        },
        container(
            "recover", [".venv/bin/python", "-m", "app.azure_worker", "--recover"]
        ),
    )
    recovery["properties"]["configuration"]["replicaTimeout"] = 240
    api = container("api")
    api["resources"] = {"cpu": "[json('0.5')]", "memory": "1Gi"}
    api["env"].append(
        {
            "name": "ALLOWED_ORIGINS",
            "value": f"[concat('https://{n['app']}.', reference(resourceId('Microsoft.App/managedEnvironments', '{n['environment']}'), '{APP_API}').defaultDomain)]",
        }
    )
    api["probes"] = [
        {
            "type": "Startup",
            "httpGet": {"path": "/health", "port": 8000},
            "periodSeconds": 5,
            "timeoutSeconds": 3,
            "failureThreshold": 60,
        },
        {
            "type": "Readiness",
            "httpGet": {"path": "/health", "port": 8000},
            "periodSeconds": 10,
            "timeoutSeconds": 3,
            "failureThreshold": 3,
        },
    ]
    web = {
        "name": "web",
        "image": f"{n['registry']}.azurecr.io/frontend:{image_tag}",
        "env": [{"name": "API_URL", "value": "http://127.0.0.1:8000"}],
        "resources": {"cpu": "[json('0.5')]", "memory": "1Gi"},
        "probes": [
            {
                "type": "Readiness",
                "httpGet": {"path": "/", "port": 3000},
                "periodSeconds": 10,
                "timeoutSeconds": 3,
                "failureThreshold": 3,
            }
        ],
    }
    app = {
        "type": "Microsoft.App/containerApps",
        "apiVersion": APP_API,
        "name": n["app"],
        "location": location,
        "identity": {"type": "UserAssigned", "userAssignedIdentities": {identity: {}}},
        "properties": {
            "environmentId": rid("Microsoft.App/managedEnvironments", n["environment"]),
            "workloadProfileName": "Consumption",
            "configuration": {
                "activeRevisionsMode": "Single",
                "secrets": secrets,
                "registries": [registry],
                "ingress": {
                    "external": True,
                    "targetPort": 3000,
                    "allowInsecure": False,
                    "transport": "auto",
                },
            },
            "template": {
                "revisionSuffix": "r"
                + sha256(
                    (image_tag + "|" + (session_key_url or "")).encode()
                ).hexdigest()[:12],
                "containers": [api, web],
                "scale": {
                    "minReplicas": 0,
                    "maxReplicas": 2,
                    "rules": [
                        {
                            "name": "http",
                            "http": {"metadata": {"concurrentRequests": "20"}},
                        }
                    ],
                },
            },
        },
    }
    return template(
        [worker, recovery, app],
        outputs={
            "url": {
                "type": "string",
                "value": f"[concat('https://', reference(resourceId('Microsoft.App/containerApps', '{n['app']}'), '{APP_API}').configuration.ingress.fqdn)]",
            },
        },
    )
