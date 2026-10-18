"use client";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Download,
  Feather,
  FileText,
  FolderOpen,
  Globe2,
  ImagePlus,
  Layers3,
  Library,
  Loader2,
  LockKeyhole,
  LogOut,
  MoreHorizontal,
  Palette,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Settings2,
  ShieldCheck,
  Sparkles,
  Square,
  Trash2,
  UsersRound,
  WandSparkles,
  X,
} from "lucide-react";
import type {
  Book,
  Character,
  CharacterData,
  Config,
  Cover,
  Job,
  LayoutElement,
  Page,
  PrintSpec,
  Project,
  ScriptData,
  Summary,
  SystemSettings,
} from "./types";

async function api<T = unknown>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...options,
    credentials: "same-origin",
    headers: {
      ...(options.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...options.headers,
    },
  });
  if (!response.ok) {
    let message = await response.text();
    try {
      const parsed = JSON.parse(message);
      message =
        typeof parsed.detail === "string"
          ? parsed.detail
          : JSON.stringify(parsed.detail);
    } catch {}
    throw new Error(message || `Request failed (${response.status})`);
  }
  return response.json();
}
const post = (body?: unknown): RequestInit => ({
  method: "POST",
  ...(body ? { body: JSON.stringify(body) } : {}),
});
const put = (body: unknown): RequestInit => ({
  method: "PUT",
  body: JSON.stringify(body),
});
const asset = (id: string, key?: string) =>
  key ? `/api/projects/${id}/assets/${key}` : "";
const money = (n = 0) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(
    n,
  );
const label = (s: string) => s.replaceAll("_", " ");
type Run = (fn: () => Promise<unknown>, message?: string) => Promise<boolean>;
type Tab = "overview" | "characters" | "editor" | "cover" | "exports";
const tabs: { id: Tab; label: string }[] = [
  { id: "overview", label: "Manuscript" },
  { id: "characters", label: "Character Studio" },
  { id: "editor", label: "Book Editor" },
  { id: "cover", label: "Cover & print" },
  { id: "exports", label: "Exports" },
];
function Button({
  children,
  onClick,
  variant = "",
  disabled = false,
  type = "button",
  title,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: string;
  disabled?: boolean;
  type?: "button" | "submit";
  title?: string;
}) {
  return (
    <button
      type={type}
      title={title}
      onClick={onClick}
      disabled={disabled}
      className={`button ${variant}`}
    >
      {children}
    </button>
  );
}
function Field({
  label: caption,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <label className="field">
      <span>{caption}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}
function Badge({
  children,
  tone = "",
}: {
  children: ReactNode;
  tone?: string;
}) {
  return <span className={`badge ${tone}`}>{children}</span>;
}
function Empty({
  icon = <BookOpen />,
  title,
  children,
}: {
  icon?: ReactNode;
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-icon">{icon}</div>
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
function BookMark({ small = false }: { small?: boolean }) {
  return (
    <div className={`book-mark ${small ? "small" : ""}`} aria-hidden="true">
      <div className="mark-orbit" />
      <div className="mark-arch" />
      <BookOpen strokeWidth={1.1} />
      <span>Α</span>
    </div>
  );
}

export default function Studio() {
  const [user, setUser] = useState<{ email: string } | null>(null),
    [loading, setLoading] = useState(true),
    [projects, setProjects] = useState<Project[]>([]),
    [selected, setSelected] = useState(""),
    [book, setBook] = useState<Book | null>(null),
    [view, setView] = useState<"books" | "new" | "settings" | "book">("books"),
    [tab, setTab] = useState<Tab>("overview"),
    [system, setSystem] = useState<SystemSettings | null>(null),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState(""),
    [error, setError] = useState("");
  const refresh = useCallback(async () => {
    const [list, config] = await Promise.all([
      api<Project[]>("/projects"),
      api<SystemSettings>("/settings"),
    ]);
    setProjects(list);
    setSystem(config);
    if (selected) setBook(await api<Book>(`/projects/${selected}`));
  }, [selected]);
  useEffect(() => {
    api<{ email: string }>("/auth/me")
      .then(setUser)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => {
    if (user) refresh().catch((e) => setError(e.message));
  }, [user, refresh]);
  useEffect(() => {
    if (!selected || !user) return;
    const source = new EventSource(`/api/projects/${selected}/events`);
    source.addEventListener("progress", () => {
      api<Book>(`/projects/${selected}`)
        .then(setBook)
        .catch(() => {});
    });
    return () => source.close();
  }, [selected, user]);
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(""), 4500);
    return () => clearTimeout(timer);
  }, [notice]);
  const run: Run = async (fn, message) => {
    setBusy(true);
    setError("");
    try {
      await fn();
      await refresh();
      if (message) setNotice(message);
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
      return false;
    } finally {
      setBusy(false);
    }
  };
  const open = (id: string, next: Tab = "overview") => {
    setSelected(id);
    setTab(next);
    setView("book");
  };
  if (loading)
    return (
      <div className="boot">
        <Library />
        <p>Opening your library…</p>
      </div>
    );
  if (!user) return <Auth onLogin={setUser} />;
  const navigation = (next: Tab) => {
    if (selected) {
      setTab(next);
      setView("book");
    } else if (projects.length) open(projects[0].id, next);
    else setView("books");
  };
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setView("books");
          }}
        >
          <Library size={31} strokeWidth={1.2} />
          <span>
            Library of
            <strong>
              Alexandria<span className="brand-period">.</span>
            </strong>
          </span>
        </a>
        <div className="workspace-label">THE PUBLISHING STUDIO</div>
        <nav aria-label="Main navigation">
          <button
            className={view === "books" ? "active" : ""}
            onClick={() => setView("books")}
          >
            <FolderOpen size={19} />
            My Books<span className="nav-count">{projects.length}</span>
          </button>
          <button
            className={view === "new" ? "active" : ""}
            onClick={() => setView("new")}
          >
            <Plus size={19} />
            New Book
          </button>
          <div className="nav-rule" />
          <button
            className={view === "book" && tab === "characters" ? "active" : ""}
            onClick={() => navigation("characters")}
          >
            <UsersRound size={19} />
            Character Studio
          </button>
          <button
            className={view === "book" && tab === "editor" ? "active" : ""}
            onClick={() => navigation("editor")}
          >
            <Layers3 size={19} />
            Book Editor
          </button>
          <button
            className={view === "book" && tab === "exports" ? "active" : ""}
            onClick={() => navigation("exports")}
          >
            <Download size={19} />
            Exports
          </button>
        </nav>
        <div className="sidebar-note">
          <Feather size={23} />
          <p>
            Every great book
            <br />
            begins with a story.
          </p>
          <span>Make yours visible.</span>
        </div>
        <div className="sidebar-bottom">
          <button
            onClick={() => setView("settings")}
            className={view === "settings" ? "active" : ""}
          >
            <Settings2 size={18} />
            Studio settings
          </button>
          <div className="profile">
            <div className="avatar">{user.email[0].toUpperCase()}</div>
            <div>
              <strong>Your workspace</strong>
              <small>{user.email}</small>
            </div>
            <button
              aria-label="Sign out"
              onClick={() =>
                api("/auth/logout", post()).then(() => {
                  setUser(null);
                  setBook(null);
                  setSelected("");
                  setProjects([]);
                })
              }
            >
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <div>
            <span>Workspace</span>
            <ChevronRight size={13} />
            <strong>
              {view === "books"
                ? "My Books"
                : view === "new"
                  ? "New Book"
                  : view === "settings"
                    ? "Settings"
                    : book?.title || "Book"}
            </strong>
          </div>
          <div className="topbar-right">
            <span className="mode-dot" />
            <span>
              {system?.ai_mode === "live" ? "Live studio" : "Offline studio"}
            </span>
            <span className="topbar-divider" />
            <span className="topbar-motto">Turn stories into worlds.</span>
            <div className="avatar light">{user.email[0].toUpperCase()}</div>
          </div>
        </header>
        <div className="main-content">
          {system?.ai_mode === "offline" && (
            <div className="offline-note">
              <FlaskIcon />
              Offline testing mode · Analysis is extractive and images are
              labeled test art.{" "}
              <button onClick={() => setView("settings")}>
                Configure live AI <ArrowRight size={12} />
              </button>
            </div>
          )}
          {error && (
            <div className="notice error" role="alert">
              <span>{error}</span>
              <button aria-label="Dismiss error" onClick={() => setError("")}>
                <X size={16} />
              </button>
            </div>
          )}
          {notice && (
            <div className="notice success" role="status">
              <CheckCircle2 size={17} />
              {notice}
            </div>
          )}
          {busy && (
            <div className="working" role="status">
              <Loader2 className="spin" size={15} />
              Saving changes…
            </div>
          )}
          {view === "books" && (
            <Dashboard
              projects={projects}
              open={open}
              create={() => setView("new")}
            />
          )}
          {view === "new" && (
            <NewBook system={system} run={run} created={(id) => open(id)} />
          )}
          {view === "settings" && <Settings system={system} />}
          {view === "book" &&
            (!book || book.id !== selected ? (
              <Empty title="Opening your book…">
                <Loader2 className="spin" />
              </Empty>
            ) : (
              <>
                <div className="book-heading">
                  <div>
                    <button
                      className="back-link"
                      onClick={() => setView("books")}
                    >
                      <ArrowLeft size={13} />
                      All books
                    </button>
                    <h1>{book.title}</h1>
                    <p>
                      By {book.author}
                      <span className="middot">·</span>
                      {book.config.book_type === "graphic"
                        ? "Graphic novel"
                        : "Illustrated novel"}
                      <span className="middot">·</span>
                      {book.config.style}
                    </p>
                  </div>
                  <div className="book-heading-status">
                    <Badge tone={book.status === "completed" ? "green" : ""}>
                      {label(book.status)}
                    </Badge>
                    <span>
                      {money(book.metrics.spent_and_reserved_usd)} /{" "}
                      {money(book.budget_usd)} budget
                    </span>
                  </div>
                </div>
                <div className="tabs" role="tablist">
                  {tabs.map((t) => (
                    <button
                      role="tab"
                      aria-selected={t.id === tab}
                      className={t.id === tab ? "selected" : ""}
                      key={t.id}
                      onClick={() => setTab(t.id)}
                    >
                      {t.label}
                      {t.id === "characters" && (
                        <span>{book.characters.length}</span>
                      )}
                    </button>
                  ))}
                </div>
                <JobMonitor book={book} run={run} busy={busy} system={system} />
                {tab === "overview" && (
                  <Overview book={book} run={run} busy={busy} />
                )}
                {tab === "characters" && (
                  <Characters book={book} run={run} busy={busy} />
                )}
                {tab === "editor" && (
                  <Editor key={book.id} book={book} run={run} busy={busy} />
                )}
                {tab === "cover" && (
                  <CoverDesigner book={book} run={run} busy={busy} />
                )}
                {tab === "exports" && (
                  <Exports book={book} run={run} busy={busy} />
                )}
              </>
            ))}
        </div>
        <footer className="footer">
          <span>LIBRARY OF ALEXANDRIA</span>
          <span>A place for stories to become something extraordinary.</span>
          <span>STUDIO / 01</span>
        </footer>
      </main>
    </div>
  );
}
function FlaskIcon() {
  return <Sparkles size={13} />;
}

function Auth({ onLogin }: { onLogin: (u: { email: string }) => void }) {
  const [signup, setSignup] = useState(true),
    [email, setEmail] = useState(""),
    [password, setPassword] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      onLogin(
        await api(
          "/auth/" + (signup ? "register" : "login"),
          post({ email, password }),
        ),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="auth-shell">
      <section className="auth-story">
        <a className="brand" href="#">
          <Library size={32} />
          <span>
            Library of<strong>Alexandria.</strong>
          </span>
        </a>
        <div className="auth-copy">
          <span className="eyebrow">THE NEXT CHAPTER OF STORYTELLING</span>
          <h1>
            A story on the page.
            <br />A world waiting
            <br />
            to be seen.
          </h1>
          <p>
            Your words, reimagined. Create beautifully illustrated books with a
            studio built for the stories that matter.
          </p>
          <BookMark />
          <span className="auth-footnote">
            MANUSCRIPT → IMAGINATION → EDITION
          </span>
        </div>
        <span className="auth-bottom">Turn stories into worlds.</span>
      </section>
      <section className="auth-form">
        <div className="auth-form-inner">
          <div className="eyebrow">YOUR INDEPENDENT PUBLISHING STUDIO</div>
          <h2>{signup ? "Begin your next chapter." : "Welcome back."}</h2>
          <p>
            {signup
              ? "Create your private workspace. A whole world is waiting."
              : "Your stories are right where you left them."}
          </p>
          <form onSubmit={submit}>
            <Field label="Email address">
              <input
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@yourstudio.com"
                required
              />
            </Field>
            <Field label="Password" hint="At least 10 characters.">
              <input
                type="password"
                autoComplete={signup ? "new-password" : "current-password"}
                minLength={10}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </Field>
            {error && (
              <p role="alert" className="form-error">
                {error}
              </p>
            )}
            <Button type="submit" disabled={busy}>
              {busy ? (
                <Loader2 className="spin" size={17} />
              ) : (
                <>
                  {signup ? "Create your studio" : "Enter your studio"}
                  <ArrowRight size={16} />
                </>
              )}
            </Button>
          </form>
          <p className="switch-auth">
            {signup ? "Already have a workspace?" : "New to Alexandria?"}{" "}
            <button
              onClick={() => {
                setSignup(!signup);
                setError("");
              }}
            >
              {signup ? "Sign in" : "Create an account"}
            </button>
          </p>
          <div className="auth-assurance">
            <ShieldCheck size={16} />
            <span>Private manuscripts. Your creative control.</span>
          </div>
        </div>
      </section>
    </div>
  );
}

function Dashboard({
  projects,
  open,
  create,
}: {
  projects: Project[];
  open: (id: string) => void;
  create: () => void;
}) {
  const totals = projects.reduce(
    (a, p) => ({
      pages: a.pages + p.metrics.pages_generated,
      characters: a.characters + p.metrics.references_approved,
      ready: a.ready + (p.metrics.qa_status === "passed" ? 1 : 0),
    }),
    { pages: 0, characters: 0, ready: 0 },
  );
  return (
    <>
      <div className="page-heading">
        <div className="eyebrow">
          <span className="tiny-line" />
          YOUR STORIES, BEAUTIFULLY REIMAGINED
        </div>
        <div className="heading-row">
          <div>
            <h1>
              A library of possibilities<span className="accent">.</span>
            </h1>
            <p>
              From the first word to the final page. This is where worlds take
              shape.
            </p>
          </div>
          <Button onClick={create}>
            <Plus size={17} />
            Create a book
          </Button>
        </div>
      </div>
      <section className="hero">
        <div className="hero-text">
          <Badge>THE ART OF A NEW EDITION</Badge>
          <h2>
            Give your story
            <br />
            another dimension.
          </h2>
          <p>
            Bring a manuscript. Find its visual language.
            <br />
            Create a book that feels entirely your own.
          </p>
          <button onClick={create}>
            Start a new chapter
            <ArrowRight size={17} />
          </button>
          <div className="hero-steps">
            <span>
              01 <strong>Import</strong>
            </span>
            <span>
              02 <strong>Imagine</strong>
            </span>
            <span>
              03 <strong>Publish</strong>
            </span>
          </div>
        </div>
        <div className="hero-art">
          <div className="art-sun" />
          <div className="art-lines" />
          <div className="display-book book-back">
            <div className="cover-border" />
            <span>
              THE ART
              <br />
              OF STORIES
            </span>
            <Feather size={32} />
          </div>
          <div className="display-book book-front">
            <div className="cover-border" />
            <span className="cover-kicker">A WORLD WITHIN</span>
            <div className="cover-window">
              <div className="moon" />
              <div className="mountain one" />
              <div className="mountain two" />
              <div className="mountain three" />
            </div>
            <strong>
              IMAGINATION
              <br />
              <em>ILLUSTRATED</em>
            </strong>
            <small>LIBRARY OF ALEXANDRIA</small>
          </div>
          <div className="art-caption">
            AN OLD LOVE FOR BOOKS.
            <br />A NEW WAY TO MAKE THEM.
          </div>
        </div>
      </section>
      <div className="stats-row">
        <Stat
          label="Books in your library"
          value={projects.length}
          icon={<BookOpen />}
        />
        <Stat
          label="Illustrated pages"
          value={totals.pages}
          icon={<Layers3 />}
        />
        <Stat
          label="Canonical characters"
          value={totals.characters}
          icon={<UsersRound />}
        />
        <Stat
          label="QA-ready editions"
          value={totals.ready}
          icon={<ShieldCheck />}
        />
      </div>
      <div className="section-heading">
        <div>
          <h2>
            Your bookshelf{" "}
            <span>{projects.length.toString().padStart(2, "0")}</span>
          </h2>
          <p>A little progress, a new world.</p>
        </div>
        <span className="muted small-text">
          <Clock size={14} />
          Recently created
        </span>
      </div>
      <div className="bookshelf">
        {projects.map((p) => (
          <button className="book-card" key={p.id} onClick={() => open(p.id)}>
            <div className="card-art">
              {p.cover?.artwork_key ? (
                <img
                  alt={`${p.title} cover`}
                  src={asset(p.id, p.cover.artwork_key)}
                />
              ) : (
                <>
                  <BookMark small />
                  <span>{p.title}</span>
                </>
              )}
              <span className="card-format">
                {p.config.book_type === "graphic"
                  ? "GRAPHIC NOVEL"
                  : "ILLUSTRATED NOVEL"}
              </span>
            </div>
            <div className="card-body">
              <div className="card-title">
                <h3>{p.title}</h3>
                <ChevronRight size={17} />
              </div>
              <p>{p.author}</p>
              <Badge tone={p.status === "completed" ? "green" : ""}>
                {label(p.status)}
              </Badge>
              <div className="card-progress">
                <span
                  style={{
                    width: `${p.metrics.pages ? (100 * p.metrics.pages_generated) / p.metrics.pages : 0}%`,
                  }}
                />
              </div>
              <div className="card-details">
                <span>
                  {p.metrics.chapters_completed}/{p.metrics.chapters} chapters
                </span>
                <span>
                  {p.metrics.pages_generated} pages ·{" "}
                  {p.metrics.references_approved} approved designs
                </span>
              </div>
              <div className="card-cost">
                <span>
                  Reserved & spent: {money(p.metrics.spent_and_reserved_usd)}
                </span>
                <span>{p.metrics.qa_status}</span>
              </div>
            </div>
          </button>
        ))}
        <button className="create-card" onClick={create}>
          <div>
            <Plus size={26} />
          </div>
          <h3>
            {projects.length
              ? "Another world awaits."
              : "Your first book starts here."}
          </h3>
          <p>
            A manuscript, an idea,
            <br />a whole new perspective.
          </p>
          <span>
            Create a book
            <ArrowRight size={15} />
          </span>
        </button>
      </div>
      <section className="workflow-strip">
        <div className="eyebrow">MADE WITH INTENTION</div>
        <div>
          <span>
            <FileText />
            <strong>Faithful to your story</strong>
            <small>Source-linked chapters and scripts</small>
          </span>
          <span>
            <UsersRound />
            <strong>Characters with continuity</strong>
            <small>Approved designs, every page</small>
          </span>
          <span>
            <Palette />
            <strong>Your creative direction</strong>
            <small>Editable art, text, and layouts</small>
          </span>
          <span>
            <ShieldCheck />
            <strong>Built for the printed page</strong>
            <small>Separate interior, cover, and QA</small>
          </span>
        </div>
      </section>
    </>
  );
}
function Stat({
  label: caption,
  value,
  icon,
}: {
  label: string;
  value: number;
  icon: ReactNode;
}) {
  return (
    <div className="stat">
      <div>
        {icon}
        <span>{caption}</span>
      </div>
      <strong>{value.toString().padStart(2, "0")}</strong>
    </div>
  );
}

const defaultConfig: Config = {
  original_language: "English",
  output_language: "English",
  book_type: "illustrated",
  pages_per_chapter: 3,
  style: "Dark Gothic Medieval Epic",
  art_description: "",
  audience: "Adults",
  tone: "Faithful, cinematic adaptation",
  edition: "Unspecified",
  text_model: "",
  image_model: "",
  quality: "low",
  print: {
    width: 6,
    height: 9,
    bleed: false,
    paper: "white",
    margin: 0.5,
    minimum_dpi: 300,
  },
};
const styleNames = [
  "Dark Gothic Medieval Epic",
  "Classical Oil Painting",
  "Realistic Cinematic",
  "European Graphic Novel",
  "Manga",
  "Watercolor Storybook",
  "Fantasy Illustration",
  "Custom",
];
function NewBook({
  system,
  run,
  created,
}: {
  system: SystemSettings | null;
  run: Run;
  created: (id: string) => void;
}) {
  const [step, setStep] = useState(0),
    [title, setTitle] = useState(""),
    [author, setAuthor] = useState(""),
    [config, setConfig] = useState<Config>(defaultConfig),
    [source, setSource] = useState<"upload" | "url">("upload"),
    [url, setUrl] = useState(""),
    [file, setFile] = useState<File | null>(null),
    [rights, setRights] = useState(false),
    [declaration, setDeclaration] = useState(""),
    [budget, setBudget] = useState(25),
    [creating, setCreating] = useState(false);
  const update = <K extends keyof Config>(key: K, value: Config[K]) =>
    setConfig((c) => ({ ...c, [key]: value }));
  async function preset() {
    const data = await api<{
      ivanhoe: {
        title: string;
        author: string;
        art_description: string;
        source_url: string;
      };
    }>("/presets");
    setTitle(data.ivanhoe.title);
    setAuthor(data.ivanhoe.author);
    setConfig((c) => ({ ...c, art_description: data.ivanhoe.art_description }));
    setUrl(data.ivanhoe.source_url);
    setSource("url");
  }
  const valid =
    title.trim() &&
    author.trim() &&
    rights &&
    declaration.length >= 8 &&
    (source === "url" ? url.trim() : file);
  async function create() {
    setCreating(true);
    await run(async () => {
      const book = await api<Project>(
        "/projects",
        post({
          title,
          author,
          ...config,
          budget_usd: budget,
          rights_confirmed: rights,
          rights_declaration: declaration,
        }),
      );
      created(book.id);
      if (source === "url")
        await api(`/projects/${book.id}/source/url`, post({ url }));
      else if (file) {
        const body = new FormData();
        body.append("file", file);
        await api(`/projects/${book.id}/source/upload`, {
          method: "POST",
          body,
        });
      }
    }, "Your book is ready for analysis.");
    setCreating(false);
  }
  return (
    <>
      <div className="page-heading">
        <div className="eyebrow">A NEW WORLD STARTS HERE</div>
        <h1>
          Let’s make a book<span className="accent">.</span>
        </h1>
        <p>Bring your story. We’ll help you see it in a new light.</p>
      </div>
      <div className="wizard-steps">
        {["The manuscript", "Creative direction", "The edition"].map(
          (name, i) => (
            <button
              key={name}
              disabled={i > 0 && !valid}
              onClick={() => setStep(i)}
              className={i === step ? "current" : i < step ? "done" : ""}
            >
              <span>
                {i < step ? (
                  <Check size={15} />
                ) : (
                  String(i + 1).padStart(2, "0")
                )}
              </span>
              {name}
              <ChevronRight size={16} />
            </button>
          ),
        )}
      </div>
      <div className="wizard-grid">
        <section className="panel wizard-panel">
          {step === 0 && (
            <>
              <div className="panel-heading">
                <h2>The story comes first.</h2>
                <p>Give your new edition a name and a manuscript.</p>
              </div>
              <div className="preset-callout">
                <div className="preset-icon">
                  <Feather size={21} />
                </div>
                <div>
                  <strong>Try a classic: Ivanhoe</strong>
                  <p>Sir Walter Scott, reimagined as a gothic medieval epic.</p>
                </div>
                <Button variant="outline small" onClick={() => preset()}>
                  Use preset
                  <ArrowRight size={14} />
                </Button>
              </div>
              <div className="form-grid">
                <Field label="Book title">
                  <input
                    aria-label="Book title"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="A story worth seeing"
                    required
                  />
                </Field>
                <Field label="Original author">
                  <input
                    value={author}
                    onChange={(e) => setAuthor(e.target.value)}
                    placeholder="Author’s name"
                    required
                  />
                </Field>
              </div>
              <div className="segmented">
                <button
                  className={source === "upload" ? "selected" : ""}
                  onClick={() => setSource("upload")}
                >
                  <FileText size={15} />
                  Upload TXT
                </button>
                <button
                  className={source === "url" ? "selected" : ""}
                  onClick={() => setSource("url")}
                >
                  <Globe2 size={15} />
                  Import from URL
                </button>
              </div>
              {source === "upload" ? (
                <label className="upload-zone">
                  <div>
                    <FileText size={27} />
                  </div>
                  <strong>{file ? file.name : "Choose your manuscript"}</strong>
                  <span>Plain text (.txt) · Up to 10 MB</span>
                  <input
                    type="file"
                    accept=".txt,text/plain"
                    onChange={(e) => setFile(e.target.files?.[0] || null)}
                  />
                </label>
              ) : (
                <Field
                  label="Public manuscript URL"
                  hint="A publicly accessible text or HTML page. Source availability depends on network access."
                >
                  <input
                    type="url"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    placeholder="https://…"
                  />
                </Field>
              )}
              <div className="form-grid">
                <Field label="Original language">
                  <input
                    value={config.original_language}
                    onChange={(e) =>
                      update("original_language", e.target.value)
                    }
                  />
                </Field>
                <Field label="Output language">
                  <input
                    value={config.output_language}
                    onChange={(e) => update("output_language", e.target.value)}
                  />
                </Field>
              </div>
              <Field label="Source edition">
                <input
                  value={config.edition}
                  onChange={(e) => update("edition", e.target.value)}
                  placeholder="Edition, translator, publication year"
                />
              </Field>
              <div className="rights-box">
                <ShieldCheck size={21} />
                <div>
                  <label className="checkbox">
                    <input
                      type="checkbox"
                      checked={rights}
                      onChange={(e) => setRights(e.target.checked)}
                    />
                    I hold the required rights, or this source is public domain
                    in my target markets.
                  </label>
                  <textarea
                    aria-label="Publishing rights declaration"
                    value={declaration}
                    onChange={(e) => setDeclaration(e.target.value)}
                    placeholder="State the rights basis and intended publishing markets…"
                    rows={2}
                  />
                  <small>
                    Public availability alone does not grant publishing rights.
                  </small>
                </div>
              </div>
            </>
          )}
          {step === 1 && (
            <>
              <div className="panel-heading">
                <h2>Find its visual language.</h2>
                <p>
                  One coherent world, from the first portrait to the last page.
                </p>
              </div>
              <Field label="Book format">
                <div className="format-options">
                  {[
                    [
                      "illustrated",
                      "Illustrated novel",
                      "Expansive artwork with readable narration",
                    ],
                    [
                      "graphic",
                      "Graphic novel",
                      "Multi-panel scenes, dialogue, and captions",
                    ],
                  ].map(([id, name, desc]) => (
                    <button
                      key={id}
                      className={config.book_type === id ? "selected" : ""}
                      onClick={() => update("book_type", id)}
                    >
                      <Layers3 size={22} />
                      <strong>{name}</strong>
                      <small>{desc}</small>
                      {config.book_type === id && <CheckCircle2 size={17} />}
                    </button>
                  ))}
                </div>
              </Field>
              <Field
                label="Pages per original chapter"
                hint="An explicit adaptation plan assigns every essential event to a page."
              >
                <input
                  type="number"
                  min={1}
                  max={5}
                  value={config.pages_per_chapter}
                  onChange={(e) =>
                    update(
                      "pages_per_chapter",
                      Math.max(1, Math.min(5, Number(e.target.value))),
                    )
                  }
                />
              </Field>
              <Field label="Art direction">
                <div className="style-grid">
                  {styleNames.map((name, i) => (
                    <button
                      key={name}
                      onClick={() => update("style", name)}
                      className={config.style === name ? "selected" : ""}
                    >
                      <span className={`style-swatch swatch-${i}`} />
                      <span>{name}</span>
                      {config.style === name && <Check size={14} />}
                    </button>
                  ))}
                </div>
              </Field>
              <Field label="Your art-style description">
                <textarea
                  rows={4}
                  value={config.art_description}
                  onChange={(e) => update("art_description", e.target.value)}
                  placeholder="Palette, lighting, atmosphere, costumes, details…"
                />
              </Field>
              <div className="form-grid">
                <Field label="Audience">
                  <input
                    value={config.audience}
                    onChange={(e) => update("audience", e.target.value)}
                  />
                </Field>
                <Field label="Narrative tone">
                  <input
                    value={config.tone}
                    onChange={(e) => update("tone", e.target.value)}
                  />
                </Field>
              </div>
            </>
          )}
          {step === 2 && (
            <>
              <div className="panel-heading">
                <h2>An edition made to hold.</h2>
                <p>
                  Set your print format and keep generation costs under control.
                </p>
              </div>
              <PrintFields
                value={config.print}
                onChange={(value) => update("print", value)}
              />
              <div className="form-divider" />
              <div className="form-grid">
                <Field
                  label="Project budget cap (USD)"
                  hint="Reserved and spent costs count toward this cap."
                >
                  <input
                    type="number"
                    min={0.1}
                    max={10000}
                    step={0.1}
                    value={budget}
                    onChange={(e) => setBudget(Number(e.target.value))}
                  />
                </Field>
                <Field label="Image quality">
                  <select
                    value={config.quality}
                    onChange={(e) => update("quality", e.target.value)}
                  >
                    <option value="low">Preview · lower cost</option>
                    <option value="medium">Medium</option>
                    <option value="high">Final · high quality</option>
                  </select>
                </Field>
              </div>
              <div className="form-grid">
                <Field label="Text model">
                  <input
                    placeholder={system?.text_model}
                    value={config.text_model}
                    onChange={(e) => update("text_model", e.target.value)}
                  />
                </Field>
                <Field label="Image model">
                  <input
                    placeholder={system?.image_model}
                    value={config.image_model}
                    onChange={(e) => update("image_model", e.target.value)}
                  />
                </Field>
              </div>
              <div className="info-box">
                <ShieldCheck size={20} />
                <p>
                  You review summaries, character designs, and page scripts
                  before artwork batches. Low-resolution artwork is flagged
                  during export; it is never mislabeled as print quality.
                </p>
              </div>
              <div className="summary-line">
                <span>{title}</span>
                <strong>{config.pages_per_chapter} pages / chapter</strong>
              </div>
            </>
          )}
          <div className="wizard-actions">
            {step > 0 ? (
              <Button variant="ghost" onClick={() => setStep(step - 1)}>
                <ArrowLeft size={15} />
                Back
              </Button>
            ) : (
              <span />
            )}
            {step < 2 ? (
              <Button disabled={!valid} onClick={() => setStep(step + 1)}>
                Continue
                <ArrowRight size={16} />
              </Button>
            ) : (
              <Button
                disabled={creating || !valid || budget <= 0}
                onClick={create}
              >
                {creating ? (
                  <Loader2 className="spin" size={16} />
                ) : (
                  <Sparkles size={16} />
                )}
                Create my book
              </Button>
            )}
          </div>
        </section>
        <aside className="wizard-aside">
          <div className="edition-preview">
            <BookMark />
            <div className="eyebrow">YOUR NEXT EDITION</div>
            <h3>{title || "An untold world"}</h3>
            <p>{author || "A story by you"}</p>
            <div className="edition-meta">
              <span>
                {config.book_type === "graphic"
                  ? "Graphic novel"
                  : "Illustrated novel"}
              </span>
              <span>
                {config.print.width} × {config.print.height} inches
              </span>
            </div>
          </div>
          <div className="aside-note">
            <Feather size={19} />
            <h4>Crafted, chapter by chapter.</h4>
            <p>
              Your original manuscript stays intact. Every adapted page links
              back to its source.
            </p>
          </div>
        </aside>
      </div>
    </>
  );
}

function PrintFields({
  value,
  onChange,
}: {
  value: PrintSpec;
  onChange: (v: PrintSpec) => void;
}) {
  const set = (key: keyof PrintSpec, v: number | string | boolean) =>
    onChange({ ...value, [key]: v });
  return (
    <>
      <div className="form-grid">
        <Field label="Trim width (in)">
          <input
            type="number"
            min={4}
            max={8.5}
            step={0.125}
            value={value.width}
            onChange={(e) => set("width", Number(e.target.value))}
          />
        </Field>
        <Field label="Trim height (in)">
          <input
            type="number"
            min={6}
            max={11.69}
            step={0.125}
            value={value.height}
            onChange={(e) => set("height", Number(e.target.value))}
          />
        </Field>
        <Field label="Paper">
          <select
            value={value.paper}
            onChange={(e) => set("paper", e.target.value)}
          >
            <option value="white">White paper</option>
            <option value="cream">Cream paper</option>
            <option value="color">Premium color</option>
          </select>
        </Field>
        <Field label="Text margin (in)">
          <input
            type="number"
            min={0.375}
            max={1.5}
            step={0.125}
            value={value.margin}
            onChange={(e) => set("margin", Number(e.target.value))}
          />
        </Field>
      </div>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={value.bleed}
          onChange={(e) => set("bleed", e.target.checked)}
        />
        Full bleed artwork
      </label>
    </>
  );
}

function JobMonitor({
  book,
  run,
  busy,
  system,
}: {
  book: Book;
  run: Run;
  busy: boolean;
  system: SystemSettings | null;
}) {
  const jobs = [...book.jobs].sort((a, b) =>
    b.created_at.localeCompare(a.created_at),
  );
  const job =
    jobs.find((j) => !["completed", "cancelled"].includes(j.status)) || jobs[0];
  if (!job) return null;
  const control = (action: string, approve_batch = false) =>
    run(
      () =>
        api(
          `/projects/${book.id}/jobs/${job.id}/control`,
          post({ action, approve_batch }),
        ),
      action === "cancel" ? "Cancellation requested." : "Job updated.",
    );
  const resumable = ["review", "paused", "failed"].includes(job.status);
  const batch =
    job.status === "review" &&
    ["generate_character_references", "generate_page_art"].includes(job.stage);
  const batchCount =
    job.stage === "generate_character_references"
      ? book.characters.filter(
          (c) => !book.references.some((r) => r.character_id === c.id),
        ).length
      : book.pages.filter((p) => !p.current_artwork_id).length;
  const imageCeiling =
    book.config.quality === "low"
      ? system?.preview_image_ceiling
      : system?.final_image_ceiling;
  return (
    <section
      className={`job-monitor ${job.status === "failed" ? "job-failed" : ""}`}
    >
      <div className="job-icon">
        {job.status === "running" ? (
          <Loader2 className="spin" size={20} />
        ) : job.status === "completed" ? (
          <CheckCircle2 size={20} />
        ) : (
          <Clock size={20} />
        )}
      </div>
      <div className="job-info">
        <div>
          <strong>
            {label(job.kind === "workflow" ? job.stage : job.kind)}
          </strong>
          <Badge>{label(job.status)}</Badge>
        </div>
        <p>
          {job.error ||
            `${job.progress}% complete · Saved work is retained across restarts.`}
        </p>
        {batch && (
          <p>
            {system?.ai_mode === "offline"
              ? "Offline batch · no API charges"
              : `${batchCount} new images · ${money(batchCount * (imageCeiling || 0))} configured image reservation; analysis and visual QA reserved separately. Cap: ${money(book.budget_usd)}.`}
          </p>
        )}
        <div className="job-progress">
          <span style={{ width: `${job.progress}%` }} />
        </div>
      </div>
      <div className="job-actions">
        {["running", "queued"].includes(job.status) && (
          <Button
            variant="outline small"
            disabled={busy}
            onClick={() => control("pause")}
          >
            <Pause size={14} />
            Pause
          </Button>
        )}
        {resumable && (
          <Button
            variant="small"
            disabled={busy}
            onClick={() =>
              control(job.status === "failed" ? "retry" : "resume", batch)
            }
          >
            <Play size={14} />
            {batch
              ? "Authorize batch & continue"
              : job.status === "failed"
                ? "Retry"
                : "Continue"}
          </Button>
        )}
        {!["completed", "cancelled"].includes(job.status) && (
          <button
            title="Cancel job"
            aria-label="Cancel job"
            disabled={busy}
            onClick={() => control("cancel")}
          >
            <Square size={14} />
          </button>
        )}
      </div>
    </section>
  );
}

function Overview({
  book,
  run,
  busy,
}: {
  book: Book;
  run: Run;
  busy: boolean;
}) {
  const [url, setUrl] = useState(""),
    [sourceMode, setSourceMode] = useState<"upload" | "url">("upload");
  const upload = (file: File) =>
    run(() => {
      const body = new FormData();
      body.append("file", file);
      return api(`/projects/${book.id}/source/upload`, {
        method: "POST",
        body,
      });
    }, "Manuscript imported.");
  return (
    <>
      <div className="detail-stats">
        <Stat
          label="Original chapters"
          value={book.chapters.length}
          icon={<FileText />}
        />
        <Stat
          label="Planned pages"
          value={book.pages.length}
          icon={<Layers3 />}
        />
        <Stat
          label="Character designs"
          value={book.characters.length}
          icon={<UsersRound />}
        />
      </div>
      {!book.sources.length ? (
        <section className="panel">
          <h2>Bring in the manuscript</h2>
          <p className="muted">
            Upload text, or import a publicly accessible source.
          </p>
          <div className="segmented">
            <button
              className={sourceMode === "upload" ? "selected" : ""}
              onClick={() => setSourceMode("upload")}
            >
              TXT upload
            </button>
            <button
              className={sourceMode === "url" ? "selected" : ""}
              onClick={() => setSourceMode("url")}
            >
              URL import
            </button>
          </div>
          {sourceMode === "upload" ? (
            <label className="upload-zone">
              <FileText />
              <strong>Choose a .txt file</strong>
              <input
                disabled={busy}
                type="file"
                accept=".txt"
                onChange={(e) => {
                  if (e.target.files?.[0]) upload(e.target.files[0]);
                }}
              />
            </label>
          ) : (
            <div className="inline-form">
              <input
                aria-label="Manuscript URL"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://…"
              />
              <Button
                disabled={busy || !url}
                onClick={() =>
                  run(
                    () => api(`/projects/${book.id}/source/url`, post({ url })),
                    "Manuscript imported.",
                  )
                }
              >
                Import
              </Button>
            </div>
          )}
        </section>
      ) : !book.chapters.length ? (
        <section className="analysis-start panel">
          <div className="empty-icon">
            <WandSparkles />
          </div>
          <h2>
            The words are here.
            <br />
            Let’s find the world within.
          </h2>
          <p>
            {book.sources[0].char_count.toLocaleString()} characters imported.
            Analyze the chapters, discover the cast, and build your adaptation
            plan.
          </p>
          <Button
            disabled={busy}
            onClick={() => run(() => api(`/projects/${book.id}/run`, post()))}
          >
            <Sparkles size={16} />
            Analyze manuscript
          </Button>
        </section>
      ) : (
        <>
          <div className="section-heading">
            <div>
              <h2>Chapter by chapter</h2>
              <p>
                Review the adaptation’s foundation before generating artwork.
              </p>
            </div>
            <Badge>
              {book.summaries.filter((s) => s.approved).length} /{" "}
              {book.chapters.length} reviewed
            </Badge>
          </div>
          <div className="chapter-list">
            {[...book.chapters]
              .sort((a, b) => a.position - b.position)
              .map((chapter) => {
                const summary = book.summaries.find(
                  (s) => s.chapter_id === chapter.id,
                );
                return (
                  <ChapterCard
                    key={`${chapter.id}-${summary?.version}-${summary?.approved}`}
                    book={book}
                    chapter={chapter}
                    summary={summary}
                    run={run}
                    busy={busy}
                  />
                );
              })}
          </div>
        </>
      )}
      {book.analysis.some((a) => a.stage === "story") && (
        <section className="panel story-analysis">
          <div className="eyebrow">THE ADAPTATION STRATEGY</div>
          <h2>Keep the heart of the story.</h2>
          <p>
            {String(
              book.analysis.find((a) => a.stage === "story")?.data
                .adaptation_strategy || "",
            )}
          </p>
          <details>
            <summary>Read full story analysis</summary>
            <pre>
              {JSON.stringify(
                book.analysis.find((a) => a.stage === "story")?.data,
                null,
                2,
              )}
            </pre>
          </details>
        </section>
      )}
    </>
  );
}
function ChapterCard({
  book,
  chapter,
  summary,
  run,
  busy,
}: {
  book: Book;
  chapter: Book["chapters"][number];
  summary?: Summary;
  run: Run;
  busy: boolean;
}) {
  const [data, setData] = useState(summary?.data),
    [source, setSource] = useState("");
  return (
    <details className="chapter-card">
      <summary>
        <span className="chapter-number">
          {String(chapter.position + 1).padStart(2, "0")}
        </span>
        <div>
          <strong>{chapter.title}</strong>
          <small>
            {chapter.end_offset - chapter.start_offset} source characters ·{" "}
            {summary?.data.events.length || 0} key events
          </small>
        </div>
        {summary?.approved ? (
          <Badge tone="green">
            <Check size={12} />
            Reviewed
          </Badge>
        ) : (
          <Badge>Review needed</Badge>
        )}
        <ChevronDown size={16} />
      </summary>
      <div className="chapter-content">
        {data ? (
          <>
            <Field label="Chapter summary">
              <textarea
                rows={6}
                value={data.summary}
                onChange={(e) => setData({ ...data, summary: e.target.value })}
              />
            </Field>
            <div className="event-list">
              <h4>Essential events</h4>
              {data.events.map((event, i) => (
                <label key={event.id}>
                  <input
                    type="checkbox"
                    checked={event.essential}
                    onChange={(e) =>
                      setData({
                        ...data,
                        events: data.events.map((v, j) =>
                          i === j ? { ...v, essential: e.target.checked } : v,
                        ),
                      })
                    }
                  />
                  <span>{event.description}</span>
                </label>
              ))}
            </div>
            <div className="inline-actions">
              <Button
                disabled={busy}
                variant="outline"
                onClick={() =>
                  run(
                    () =>
                      api(
                        `/projects/${book.id}/summaries/${summary!.id}`,
                        put({ data, approved: false }),
                      ),
                    "Summary saved.",
                  )
                }
              >
                Save draft
              </Button>
              <Button
                disabled={busy}
                onClick={() =>
                  run(
                    () =>
                      api(
                        `/projects/${book.id}/summaries/${summary!.id}`,
                        put({ data, approved: true }),
                      ),
                    "Chapter approved.",
                  )
                }
              >
                <Check size={15} />
                Approve summary
              </Button>
              <button
                className="text-button"
                onClick={async () => {
                  const result = await api<{ text: string }>(
                    `/projects/${book.id}/source/text?start=${chapter.start_offset}&end=${Math.min(chapter.end_offset, chapter.start_offset + 20000)}`,
                  );
                  setSource(result.text);
                }}
              >
                View source passage
              </button>
            </div>
            {source && <pre className="source-passage">{source}</pre>}
          </>
        ) : (
          <p>Analysis is in progress. The summary will appear here.</p>
        )}
      </div>
    </details>
  );
}

function Characters({
  book,
  run,
  busy,
}: {
  book: Book;
  run: Run;
  busy: boolean;
}) {
  const [selected, setSelected] = useState("");
  const character = book.characters.find((c) => c.id === selected);
  return (
    <>
      <div className="section-heading">
        <div>
          <div className="eyebrow">A CAST THAT STAYS IN CHARACTER</div>
          <h2>The faces of your world.</h2>
          <p>Refine a design. Approve a reference. Make it canonical.</p>
        </div>
        <Badge tone="green">
          <LockKeyhole size={12} />
          {book.characters.filter((c) => c.locked).length} locked designs
        </Badge>
      </div>
      {!book.characters.length ? (
        <Empty
          icon={<UsersRound />}
          title="Your cast is waiting in the manuscript."
        >
          Analyze your manuscript to discover principal and supporting
          characters.
        </Empty>
      ) : (
        <div className="character-grid">
          {book.characters.map((c) => {
            const refs = book.references
                .filter((r) => r.character_id === c.id)
                .sort((a, b) => b.version - a.version),
              ref =
                refs.find((r) => r.id === c.approved_reference_id) || refs[0];
            return (
              <button
                className="character-card"
                key={c.id}
                onClick={() => setSelected(c.id)}
              >
                <div className="portrait">
                  {ref ? (
                    <img
                      src={asset(book.id, ref.storage_key)}
                      alt={`${c.name} reference portrait`}
                    />
                  ) : (
                    <>
                      <UsersRound size={40} strokeWidth={1} />
                      <span>DESIGN AWAITING REFERENCE</span>
                    </>
                  )}
                  <Badge tone={c.locked ? "green" : ""}>
                    {c.locked ? (
                      <LockKeyhole size={11} />
                    ) : (
                      <Palette size={11} />
                    )}{" "}
                    {c.locked ? "Canonical" : "Draft"}
                  </Badge>
                </div>
                <div>
                  <h3>{c.name}</h3>
                  <p>{c.data.role}</p>
                  <span>
                    {refs.length
                      ? `Reference v${ref?.version} · ${refs.length} versions`
                      : "No reference yet"}
                    <ArrowRight size={14} />
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      )}
      {character && (
        <CharacterDrawer
          key={`${character.id}-${character.locked}`}
          book={book}
          character={character}
          run={run}
          busy={busy}
          close={() => setSelected("")}
        />
      )}
    </>
  );
}
function CharacterDrawer({
  book,
  character,
  run,
  busy,
  close,
}: {
  book: Book;
  character: Character;
  run: Run;
  busy: boolean;
  close: () => void;
}) {
  const [data, setData] = useState<CharacterData>(character.data),
    [refId, setRefId] = useState(character.approved_reference_id || "");
  const refs = book.references
    .filter((r) => r.character_id === character.id)
    .sort((a, b) => b.version - a.version);
  const ref = refs.find((r) => r.id === refId) || refs[0];
  return (
    <div className="drawer-backdrop" onClick={close}>
      <section
        role="dialog"
        aria-modal="true"
        aria-label={`${character.name} character design`}
        className="character-drawer"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="drawer-heading">
          <div>
            <div className="eyebrow">CHARACTER STUDIO</div>
            <h2>{character.name}</h2>
          </div>
          <button aria-label="Close character" onClick={close}>
            <X />
          </button>
        </div>
        <div className="drawer-body">
          <div className="drawer-reference">
            {ref ? (
              <img
                alt="Selected canonical reference"
                src={asset(book.id, ref.storage_key)}
              />
            ) : (
              <Empty title="A face to remember.">
                Generate or upload the first reference.
              </Empty>
            )}
          </div>
          {refs.length > 0 && (
            <Field label="Reference version">
              <select
                value={ref?.id}
                onChange={(e) => setRefId(e.target.value)}
              >
                {refs.map((r) => (
                  <option key={r.id} value={r.id}>
                    Version {r.version}
                    {r.id === character.approved_reference_id
                      ? " · approved"
                      : ""}
                  </option>
                ))}
              </select>
            </Field>
          )}
          <div className="inline-actions">
            <Button
              disabled={busy || character.locked}
              variant="outline"
              onClick={() =>
                run(() =>
                  api(
                    `/projects/${book.id}/characters/${character.id}/generate`,
                    post(),
                  ),
                )
              }
            >
              <WandSparkles size={15} />
              Generate portrait
            </Button>
            <label
              className={`button outline upload-button ${character.locked ? "disabled" : ""}`}
            >
              <ImagePlus size={15} />
              Upload reference
              <input
                disabled={character.locked || busy}
                type="file"
                accept="image/png,image/jpeg,image/webp"
                onChange={(e) => {
                  if (e.target.files?.[0]) {
                    const body = new FormData();
                    body.append("file", e.target.files[0]);
                    run(
                      () =>
                        api(
                          `/projects/${book.id}/characters/${character.id}/upload`,
                          { method: "POST", body },
                        ),
                      "Reference uploaded.",
                    );
                  }
                }}
              />
            </label>
          </div>
          {character.locked ? (
            <div className="lock-banner">
              <LockKeyhole size={17} />
              <span>
                This design is canonical. Page regeneration preserves it.
              </span>
              <button
                onClick={() =>
                  run(() =>
                    api(
                      `/projects/${book.id}/characters/${character.id}/unlock`,
                      post(),
                    ),
                  )
                }
              >
                Unlock
              </button>
            </div>
          ) : (
            ref && (
              <Button
                disabled={busy}
                onClick={() =>
                  run(
                    () =>
                      api(
                        `/projects/${book.id}/characters/${character.id}/approve`,
                        post({ reference_id: ref.id }),
                      ),
                    "Reference approved and locked.",
                  )
                }
              >
                <LockKeyhole size={15} />
                Approve & lock this reference
              </Button>
            )
          )}
          <div className="form-divider" />
          {(
            [
              "name",
              "role",
              "age",
              "appearance",
              "hair",
              "eyes",
              "face",
              "body",
              "personality",
              "clothing",
              "visual_description",
              "consistency",
              "arc",
            ] as const
          ).map((key) => (
            <Field key={key} label={label(key)}>
              {[
                "appearance",
                "visual_description",
                "consistency",
                "arc",
              ].includes(key) ? (
                <textarea
                  rows={3}
                  disabled={character.locked}
                  value={data[key]}
                  onChange={(e) => setData({ ...data, [key]: e.target.value })}
                />
              ) : (
                <input
                  disabled={character.locked}
                  value={data[key]}
                  onChange={(e) => setData({ ...data, [key]: e.target.value })}
                />
              )}
            </Field>
          ))}
          {(
            [
              "aliases",
              "accessories",
              "relationships",
              "timeline",
              "alternate_designs",
            ] as const
          ).map((key) => (
            <Field key={key} label={label(key)} hint="One entry per line">
              <textarea
                rows={2}
                disabled={character.locked}
                value={data[key].join("\n")}
                onChange={(e) =>
                  setData({
                    ...data,
                    [key]: e.target.value.split("\n").filter(Boolean),
                  })
                }
              />
            </Field>
          ))}
          <Button
            disabled={busy || character.locked}
            onClick={() =>
              run(
                () =>
                  api(
                    `/projects/${book.id}/characters/${character.id}`,
                    put({ data }),
                  ),
                "Character bible saved.",
              )
            }
          >
            Save character details
          </Button>
        </div>
      </section>
    </div>
  );
}

function PageCanvas({
  book,
  page,
  elements,
  onMove,
  activeElement = -1,
  onSelect,
}: {
  book: Book;
  page: Page;
  elements: LayoutElement[];
  onMove?: (i: number, x: number, y: number) => void;
  activeElement?: number;
  onSelect?: (i: number) => void;
}) {
  const ref = useRef<HTMLDivElement>(null),
    drag = useRef<{ index: number; dx: number; dy: number } | null>(null);
  const art = book.artworks.find((a) => a.id === page.current_artwork_id);
  return (
    <div
      className="page-canvas"
      ref={ref}
      style={{
        aspectRatio: `${book.config.print.width}/${book.config.print.height}`,
      }}
    >
      {art ? (
        <img
          draggable={false}
          src={asset(book.id, art.storage_key)}
          alt={`Illustration for page ${page.position + 1}`}
        />
      ) : (
        <div className="canvas-placeholder">
          <ImagePlus size={38} strokeWidth={1} />
          <span>Art begins with an approved script.</span>
        </div>
      )}
      {elements.map((el, i) => (
        <div
          role={onMove ? "button" : undefined}
          tabIndex={onMove ? 0 : undefined}
          aria-label={onMove ? `Select ${el.kind} element ${i + 1}` : undefined}
          onKeyDown={(e) => {
            if (e.key === "Enter") onSelect?.(i);
          }}
          key={el.id || i}
          className={`page-element ${el.kind} ${activeElement === i ? "selected" : ""}`}
          style={{
            left: `${el.data.x * 100}%`,
            top: `${el.data.y * 100}%`,
            width: `${el.data.width * 100}%`,
            height: `${el.data.height * 100}%`,
            fontSize: `${(el.data.font_size * 100) / (book.config.print.width * 72)}cqw`,
            cursor: onMove ? "move" : "default",
          }}
          onPointerDown={(e) => {
            if (!onMove) return;
            e.preventDefault();
            onSelect?.(i);
            const rect = ref.current!.getBoundingClientRect();
            drag.current = {
              index: i,
              dx: (e.clientX - rect.left) / rect.width - el.data.x,
              dy: (e.clientY - rect.top) / rect.height - el.data.y,
            };
            e.currentTarget.setPointerCapture(e.pointerId);
          }}
          onPointerMove={(e) => {
            if (!drag.current || !onMove) return;
            const rect = ref.current!.getBoundingClientRect();
            onMove(
              i,
              Math.max(
                0,
                Math.min(
                  1 - el.data.width,
                  (e.clientX - rect.left) / rect.width - drag.current.dx,
                ),
              ),
              Math.max(
                0,
                Math.min(
                  1 - el.data.height,
                  (e.clientY - rect.top) / rect.height - drag.current.dy,
                ),
              ),
            );
          }}
          onPointerUp={() => {
            drag.current = null;
          }}
        >
          {el.data.text}
        </div>
      ))}
    </div>
  );
}

function Editor({ book, run, busy }: { book: Book; run: Run; busy: boolean }) {
  const [selected, setSelected] = useState(""),
    [script, setScript] = useState<ScriptData | null>(null),
    [elements, setElements] = useState<LayoutElement[]>([]),
    [layout, setLayout] = useState("illustrated"),
    [approved, setApproved] = useState(false),
    [scriptApproved, setScriptApproved] = useState(false),
    [element, setElement] = useState(-1),
    [facing, setFacing] = useState(false),
    [source, setSource] = useState("");
  const pages = [...book.pages].sort((a, b) => a.position - b.position);
  const page = pages.find((p) => p.id === selected) || pages[0];
  const stored = book.scripts.find((s) => s.page_id === page?.id);
  useEffect(() => {
    if (!page || !stored) return;
    setScript(structuredClone(stored.data));
    setLayout(page.layout);
    setApproved(page.approved);
    setScriptApproved(stored.approved);
    setElements(book.elements.filter((e) => e.page_id === page.id));
    setElement(-1);
    setSource("");
  }, [page?.id, stored?.version, page?.approved, stored?.approved]); // Preserve drafts across background progress updates.
  if (!page || !script)
    return (
      <Empty icon={<Layers3 />} title="A blank canvas, for now.">
        Approve the character references and continue the workflow to plan and
        script your pages.
        {book.chapters.length > 0 && (
          <Button
            variant="outline small"
            disabled={busy}
            onClick={() =>
              run(() =>
                api<{ id: string }>(
                  `/projects/${book.id}/pages`,
                  post({ chapter_id: book.chapters[0].id }),
                ).then((p) => setSelected(p.id)),
              )
            }
          >
            <Plus size={13} />
            Insert a page
          </Button>
        )}
      </Empty>
    );
  const root = `/projects/${book.id}`;
  const next = pages[pages.indexOf(page) + 1];
  const current = elements[element];
  const save = (approve = false) =>
    run(
      () =>
        api(
          `${root}/pages/${page.id}`,
          put({
            script,
            script_approved: approve || scriptApproved,
            approved,
            layout,
            elements: elements.map((e) => ({ kind: e.kind, ...e.data })),
          }),
        ),
      approve ? "Page script approved." : "Page saved.",
    );
  const change = <K extends keyof ScriptData>(key: K, value: ScriptData[K]) => {
    setScript({ ...script, [key]: value });
    setScriptApproved(false);
    setApproved(false);
  };
  const add = (kind: string) => {
    setElements([
      ...elements,
      {
        kind,
        data: {
          text: kind === "speech" ? "Your dialogue here" : "Your caption here",
          x: 0.1,
          y: 0.1,
          width: 0.65,
          height: 0.12,
          font_size: 12,
        },
      },
    ]);
    setElement(elements.length);
    setApproved(false);
  };
  const move = (direction: number) => {
    const order = pages.map((p) => p.id),
      index = order.indexOf(page.id),
      other = index + direction;
    if (other < 0 || other >= order.length) return;
    [order[index], order[other]] = [order[other], order[index]];
    run(
      () => api(`${root}/page-order`, put({ ids: order })),
      "Page order updated.",
    );
  };
  return (
    <div className="editor">
      <aside className="page-tree">
        <div className="editor-pane-heading">
          <h3>Pages</h3>
          <Badge>{pages.length}</Badge>
        </div>
        {[...book.chapters]
          .sort((a, b) => a.position - b.position)
          .map((ch) => (
            <div key={ch.id} className="tree-chapter">
              <h4>
                <ChevronDown size={12} />
                {ch.title}
              </h4>
              {pages
                .filter((p) => p.chapter_id === ch.id)
                .map((p) => (
                  <button
                    className={p.id === page.id ? "selected" : ""}
                    key={p.id}
                    onClick={() => setSelected(p.id)}
                  >
                    <span className="page-mini">
                      {p.current_artwork_id ? (
                        <img
                          src={asset(
                            book.id,
                            book.artworks.find(
                              (a) => a.id === p.current_artwork_id,
                            )?.storage_key,
                          )}
                          alt=""
                        />
                      ) : (
                        <FileText size={15} />
                      )}
                    </span>
                    <span>
                      Page {p.position + 1}
                      <small>
                        {p.approved
                          ? "Approved"
                          : book.scripts.find((s) => s.page_id === p.id)
                                ?.approved
                            ? "Script ready"
                            : "Draft"}
                      </small>
                    </span>
                    {p.approved && <Check size={12} />}
                  </button>
                ))}
              <button
                className="insert-page"
                disabled={busy}
                onClick={() =>
                  run(() =>
                    api<{ id: string }>(
                      `${root}/pages`,
                      post({ chapter_id: ch.id }),
                    ).then((p) => setSelected(p.id)),
                  )
                }
              >
                <Plus size={12} />
                Insert page
              </button>
            </div>
          ))}
      </aside>
      <section className="canvas-area">
        <div className="canvas-toolbar">
          <span>
            PAGE {page.position + 1}{" "}
            <span className="muted">/ {pages.length}</span>
          </span>
          <div>
            <button
              title="Move page earlier"
              aria-label="Move page earlier"
              onClick={() => move(-1)}
            >
              <ArrowUp size={15} />
            </button>
            <button
              title="Move page later"
              aria-label="Move page later"
              onClick={() => move(1)}
            >
              <ArrowDown size={15} />
            </button>
            <button
              className={facing ? "on" : ""}
              onClick={() => setFacing(!facing)}
            >
              <BookOpen size={15} />
              <span>Facing pages</span>
            </button>
          </div>
        </div>
        <div className={`canvas-desk ${facing ? "facing" : ""}`}>
          <PageCanvas
            book={book}
            page={page}
            elements={elements}
            activeElement={element}
            onSelect={setElement}
            onMove={(i, x, y) => {
              setElements((es) =>
                es.map((e, j) =>
                  i === j ? { ...e, data: { ...e.data, x, y } } : e,
                ),
              );
              setApproved(false);
            }}
          />
          {facing && next && (
            <PageCanvas
              book={book}
              page={next}
              elements={book.elements.filter((e) => e.page_id === next.id)}
            />
          )}
        </div>
        <div className="canvas-foot">
          <span>
            {book.config.print.width} × {book.config.print.height} in
          </span>
          <span>Text remains editable · Drag to position</span>
          <Badge tone={page.approved ? "green" : ""}>
            {page.approved ? "Approved" : "In review"}
          </Badge>
        </div>
        <div className="editor-actions">
          <Button
            variant="outline small"
            disabled={busy}
            onClick={() => save()}
          >
            Save page
          </Button>
          <Button variant="small" disabled={busy} onClick={() => save(true)}>
            <Check size={14} />
            Approve script
          </Button>
        </div>
      </section>
      <aside className="properties">
        <div className="editor-pane-heading">
          <h3>Page direction</h3>
          <MoreHorizontal size={17} />
        </div>
        <Field label="Layout">
          <select
            value={layout}
            onChange={(e) => {
              setLayout(e.target.value);
              setApproved(false);
            }}
          >
            <option value="illustrated">Illustration + text</option>
            <option value="panels">Graphic panels</option>
            <option value="full_bleed">Full-page art</option>
          </select>
        </Field>
        <Field label="Narration">
          <textarea
            rows={5}
            value={script.narration}
            onChange={(e) => change("narration", e.target.value)}
          />
        </Field>
        <button
          className="text-button"
          onClick={() => {
            setElements((es) =>
              es.some((e) => e.kind === "narration")
                ? es.map((e) =>
                    e.kind === "narration"
                      ? { ...e, data: { ...e.data, text: script.narration } }
                      : e,
                  )
                : [
                    ...es,
                    {
                      kind: "narration",
                      data: {
                        text: script.narration,
                        x: 0.08,
                        y: 0.72,
                        width: 0.84,
                        height: 0.2,
                        font_size: 12,
                      },
                    },
                  ],
            );
          }}
        >
          Apply narration to layout
          <ArrowDown size={12} />
        </button>
        <Field label="Scene">
          <textarea
            rows={2}
            value={script.scene}
            onChange={(e) => change("scene", e.target.value)}
          />
        </Field>
        <Field label="Illustration prompt">
          <textarea
            rows={4}
            value={script.image_prompt}
            onChange={(e) => change("image_prompt", e.target.value)}
          />
        </Field>
        <Field label="Visible characters">
          <select
            multiple
            value={script.characters}
            onChange={(e) =>
              change(
                "characters",
                Array.from(e.target.selectedOptions, (o) => o.value),
              )
            }
          >
            {book.characters.map((c) => (
              <option value={c.name} key={c.id}>
                {c.locked ? "✓ " : ""}
                {c.name}
              </option>
            ))}
          </select>
        </Field>
        <div className="reference-chips">
          {book.characters
            .filter((c) => script.characters.includes(c.name))
            .map((c) => {
              const ref = book.references.find(
                (r) => r.id === c.approved_reference_id,
              );
              return (
                <span key={c.id}>
                  {ref && <img src={asset(book.id, ref.storage_key)} alt="" />}
                  {c.name}
                  {c.locked && <LockKeyhole size={10} />}
                </span>
              );
            })}
        </div>
        <Field label="Location">
          <input
            value={script.location}
            onChange={(e) => change("location", e.target.value)}
          />
        </Field>
        <div className="form-grid">
          <Field label="Time">
            <input
              value={script.time_of_day}
              onChange={(e) => change("time_of_day", e.target.value)}
            />
          </Field>
          <Field label="Tone">
            <input
              value={script.emotional_tone}
              onChange={(e) => change("emotional_tone", e.target.value)}
            />
          </Field>
        </div>
        <Field label="Continuity (one per line)">
          <textarea
            rows={2}
            value={script.continuity.join("\n")}
            onChange={(e) => change("continuity", e.target.value.split("\n"))}
          />
        </Field>
        {script.panels.length > 0 && (
          <details>
            <summary>Panel scripts & dialogue</summary>
            {script.panels.map((p, i) => (
              <div className="panel-script" key={i}>
                <h4>Panel {i + 1}</h4>
                <Field label="Scene">
                  <textarea
                    value={p.scene}
                    onChange={(e) =>
                      change(
                        "panels",
                        script.panels.map((v, j) =>
                          i === j ? { ...v, scene: e.target.value } : v,
                        ),
                      )
                    }
                  />
                </Field>
                <Field label="Narration">
                  <textarea
                    value={p.narration}
                    onChange={(e) =>
                      change(
                        "panels",
                        script.panels.map((v, j) =>
                          i === j ? { ...v, narration: e.target.value } : v,
                        ),
                      )
                    }
                  />
                </Field>
                <Field label="Dialogue (one line per bubble)">
                  <textarea
                    value={p.dialogue.join("\n")}
                    onChange={(e) =>
                      change(
                        "panels",
                        script.panels.map((v, j) =>
                          i === j
                            ? {
                                ...v,
                                dialogue: e.target.value
                                  .split("\n")
                                  .filter(Boolean),
                              }
                            : v,
                        ),
                      )
                    }
                  />
                </Field>
              </div>
            ))}
          </details>
        )}
        <div className="form-divider" />
        <h4>Editable typography</h4>
        <div className="inline-actions">
          <Button variant="outline small" onClick={() => add("speech")}>
            <Plus size={12} />
            Speech
          </Button>
          <Button variant="outline small" onClick={() => add("caption")}>
            <Plus size={12} />
            Caption
          </Button>
        </div>
        {elements.map((el, i) => (
          <button
            key={i}
            className={`element-row ${element === i ? "selected" : ""}`}
            onClick={() => setElement(i)}
          >
            <FileText size={12} />
            <span>
              {el.kind} · {el.data.text.slice(0, 25)}
            </span>
          </button>
        ))}
        {current && (
          <div className="element-editor">
            <Field label="Element text">
              <textarea
                rows={3}
                value={current.data.text}
                onChange={(e) => {
                  setElements((es) =>
                    es.map((v, i) =>
                      i === element
                        ? { ...v, data: { ...v.data, text: e.target.value } }
                        : v,
                    ),
                  );
                  setApproved(false);
                }}
              />
            </Field>
            <div className="form-grid">
              {(["x", "y", "width", "height", "font_size"] as const).map(
                (key) => (
                  <Field
                    key={key}
                    label={
                      key === "font_size" ? "Font size (pt)" : `${key} (%)`
                    }
                  >
                    <input
                      type="number"
                      step={key === "font_size" ? 1 : 0.5}
                      value={Number(
                        (
                          current.data[key] * (key === "font_size" ? 1 : 100)
                        ).toFixed(1),
                      )}
                      onChange={(e) => {
                        setElements((es) =>
                          es.map((v, i) =>
                            i === element
                              ? {
                                  ...v,
                                  data: {
                                    ...v.data,
                                    [key]:
                                      Number(e.target.value) /
                                      (key === "font_size" ? 1 : 100),
                                  },
                                }
                              : v,
                          ),
                        );
                        setApproved(false);
                      }}
                    />
                  </Field>
                ),
              )}
            </div>
            <button
              className="danger text-button"
              onClick={() => {
                setElements((es) => es.filter((_, i) => i !== element));
                setElement(-1);
                setApproved(false);
              }}
            >
              <Trash2 size={12} />
              Remove element
            </button>
          </div>
        )}
        <div className="form-divider" />
        <Button
          disabled={busy || !stored?.approved}
          variant="outline"
          onClick={() =>
            run(() => api(`${root}/pages/${page.id}/generate`, post()))
          }
        >
          <RefreshCw size={14} />
          {page.current_artwork_id ? "Regenerate art" : "Generate art"}
        </Button>
        <small className="muted">
          Uses saved, approved script and canonical image references. Save edits
          first.
        </small>
        <label className="button outline upload-button">
          <ImagePlus size={14} />
          Upload page artwork
          <input
            type="file"
            disabled={busy}
            accept="image/png,image/jpeg,image/webp"
            onChange={(e) => {
              if (e.target.files?.[0]) {
                const body = new FormData();
                body.append("file", e.target.files[0]);
                run(
                  () =>
                    api(`${root}/pages/${page.id}/upload`, {
                      method: "POST",
                      body,
                    }),
                  "Artwork uploaded. Review resolution and character identity before approval.",
                );
              }
            }}
          />
        </label>
        <Button
          variant="outline small"
          disabled={busy || !page.current_artwork_id}
          onClick={() => run(() => api(`${root}/pages/${page.id}/qa`, post()))}
        >
          <ShieldCheck size={14} />
          Run visual QA
        </Button>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={approved}
            onChange={(e) => setApproved(e.target.checked)}
            disabled={!page.current_artwork_id}
          />
          Approve this page
        </label>
        <Button disabled={busy} onClick={() => save()}>
          Save changes
        </Button>
        <div className="form-divider" />
        <button
          className="text-button"
          onClick={async () => {
            const passage = script.source_passages[0];
            if (passage) {
              const result = await api<{ text: string }>(
                `${root}/source/text?start=${passage.start}&end=${Math.min(passage.end, passage.start + 20000)}`,
              );
              setSource(result.text);
            }
          }}
        >
          <FileText size={13} />
          View source reference
        </button>
        {source && <pre className="source-passage">{source}</pre>}
        <button
          className="danger text-button"
          disabled={busy}
          onClick={() => {
            if (
              window.confirm(
                "Delete this page? Its script will remain in the audit history.",
              )
            )
              run(() => api(`${root}/pages/${page.id}`, { method: "DELETE" }));
          }}
        >
          <Trash2 size={13} />
          Delete page
        </button>
      </aside>
    </div>
  );
}

function CoverDesigner({
  book,
  run,
  busy,
}: {
  book: Book;
  run: Run;
  busy: boolean;
}) {
  const [cover, setCover] = useState<Cover>(book.cover),
    [print, setPrint] = useState(book.config.print);
  useEffect(
    () => setCover(book.cover),
    [book.cover.artwork_key, book.cover.artwork_approved],
  );
  const set = (key: keyof Cover, value: string | boolean) =>
    setCover({ ...cover, [key]: value });
  return (
    <div className="cover-grid">
      <section>
        <div className="section-heading">
          <div>
            <div className="eyebrow">THE FIRST IMPRESSION</div>
            <h2>A cover worthy of the story.</h2>
            <p>Separate artwork. Deterministic title and author typography.</p>
          </div>
        </div>
        <div className="cover-desk">
          <div
            className="cover-preview"
            style={{ aspectRatio: `${print.width}/${print.height}` }}
          >
            {book.cover.artwork_key ? (
              <img
                src={asset(book.id, book.cover.artwork_key)}
                alt="Front cover artwork"
              />
            ) : (
              <BookMark />
            )}
            <div>
              <span>{cover.series}</span>
              <h2>{cover.title || book.title}</h2>
              <p>{cover.subtitle}</p>
              <strong>{cover.author || book.author}</strong>
            </div>
          </div>
        </div>
        <div className="inline-actions cover-buttons">
          <Button
            disabled={busy}
            onClick={() =>
              run(() => api(`/projects/${book.id}/cover/generate`, post()))
            }
          >
            <WandSparkles size={16} />
            Generate cover art
          </Button>
          <label className="button outline upload-button">
            <ImagePlus size={15} />
            Upload artwork
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp"
              disabled={busy}
              onChange={(e) => {
                if (e.target.files?.[0]) {
                  const body = new FormData();
                  body.append("file", e.target.files[0]);
                  run(() =>
                    api(`/projects/${book.id}/cover/upload`, {
                      method: "POST",
                      body,
                    }),
                  );
                }
              }}
            />
          </label>
        </div>
        <div className="info-box">
          <BookOpen size={21} />
          <p>
            Export creates a complete wraparound PDF: back cover, calculated
            spine, and front cover. Spine width uses the exported page count and
            selected paper.
          </p>
        </div>
      </section>
      <section className="panel cover-fields">
        <h3>Cover details</h3>
        {(
          [
            "title",
            "subtitle",
            "author",
            "adaptation_credit",
            "series",
            "volume",
            "publisher",
            "back_text",
          ] as const
        ).map((key) => (
          <Field
            key={key}
            label={key === "author" ? "Original author" : label(key)}
          >
            {key === "back_text" ? (
              <textarea
                rows={5}
                value={cover[key] || ""}
                onChange={(e) => set(key, e.target.value)}
              />
            ) : (
              <input
                value={cover[key] || ""}
                onChange={(e) => set(key, e.target.value)}
              />
            )}
          </Field>
        ))}
        <label className="checkbox">
          <input
            type="checkbox"
            checked={cover.artwork_approved || false}
            disabled={!book.cover.artwork_key}
            onChange={(e) => set("artwork_approved", e.target.checked)}
          />
          Approve cover artwork
        </label>
        <Button
          disabled={busy}
          onClick={() =>
            run(
              () =>
                api(
                  `/projects/${book.id}/cover`,
                  put({
                    title: cover.title || book.title,
                    author: cover.author || book.author,
                    ...cover,
                  }),
                ),
              "Cover details saved.",
            )
          }
        >
          Save cover
        </Button>
        <div className="form-divider" />
        <h3>Print specifications</h3>
        <PrintFields value={print} onChange={setPrint} />
        <Button
          disabled={busy}
          variant="outline"
          onClick={() =>
            run(
              () => api(`/projects/${book.id}/print`, put(print)),
              "Print settings saved.",
            )
          }
        >
          Save print settings
        </Button>
        <div className="form-divider" />
        <h3>Global style references</h3>
        <p className="muted small-text">
          Optional images guide new portraits, pages, and covers. Adding one
          requires reviewing existing page and cover approvals again.
        </p>
        <div className="reference-chips">
          {book.config.style_reference_keys?.map((key) => (
            <span key={key}>
              <img src={asset(book.id, key)} alt="Global art-style reference" />
              Style reference
            </span>
          ))}
        </div>
        <label className="button outline upload-button">
          <ImagePlus size={14} />
          Upload style reference
          <input
            type="file"
            disabled={
              busy || (book.config.style_reference_keys?.length || 0) >= 3
            }
            accept="image/png,image/jpeg,image/webp"
            onChange={(e) => {
              if (e.target.files?.[0]) {
                const body = new FormData();
                body.append("file", e.target.files[0]);
                run(
                  () =>
                    api(`/projects/${book.id}/style/references`, {
                      method: "POST",
                      body,
                    }),
                  "Style reference saved for future generation.",
                );
              }
            }}
          />
        </label>
      </section>
    </div>
  );
}

function Exports({ book, run, busy }: { book: Book; run: Run; busy: boolean }) {
  return (
    <>
      <div className="section-heading">
        <div>
          <div className="eyebrow">FROM YOUR STUDIO TO THE PRINTED PAGE</div>
          <h2>The final edition.</h2>
          <p>
            Single-page interiors, a wraparound cover, and a transparent quality
            report.
          </p>
        </div>
        <Button
          disabled={busy || !book.pages.length || !book.cover.artwork_key}
          onClick={() =>
            run(
              () => api(`/projects/${book.id}/exports`, post()),
              "Export package created. Review its QA report before publication.",
            )
          }
        >
          <Download size={16} />
          Create export package
        </Button>
      </div>
      <div className="info-box">
        <ShieldCheck size={22} />
        <p>
          Proofs may include QA warnings. An export is marked publication-ready
          only if its checks pass. Verify the current KDP cover template and
          market-specific publishing rights before uploading. Print PDFs are not
          Kindle eBooks.
        </p>
      </div>
      {!book.exports.length ? (
        <Empty
          icon={<Download />}
          title="A finished book is worth the details."
        >
          Generate your pages and cover, then export the complete print package.
        </Empty>
      ) : (
        <div className="exports-list">
          {[...book.exports].reverse().map((ex) => (
            <section className="panel export-card" key={ex.id}>
              <div className="section-heading">
                <div>
                  <h3>{book.title} — Print edition</h3>
                  <p>
                    {new Date(ex.created_at).toLocaleString()} ·{" "}
                    {ex.manifest.page_count} pages ·{" "}
                    {ex.manifest.spine_inches.toFixed(4)} in spine
                  </p>
                </div>
                <Badge
                  tone={ex.manifest.qa.publication_ready ? "green" : "amber"}
                >
                  {ex.manifest.qa.publication_ready ? (
                    <CheckCircle2 size={12} />
                  ) : (
                    <Clock size={12} />
                  )}{" "}
                  {ex.manifest.qa.publication_ready
                    ? "QA passed"
                    : "Proof · review required"}
                </Badge>
              </div>
              <div className="export-downloads">
                {[
                  [
                    "Interior PDF",
                    ex.interior_key,
                    "Single pages, embedded fonts",
                  ],
                  ["Wraparound cover", ex.cover_key, "Front, spine, and back"],
                  [
                    "Complete package",
                    ex.zip_key,
                    "Both PDFs, QA report, manifest",
                  ],
                ].map(([name, key, description]) => (
                  <a href={asset(book.id, key)} download key={name}>
                    <FileText size={23} />
                    <strong>{name}</strong>
                    <small>{description}</small>
                    <Download size={17} />
                  </a>
                ))}
              </div>
              {ex.manifest.qa.warnings.length > 0 && (
                <details className="qa-warnings" open>
                  <summary>
                    {ex.manifest.qa.warnings.length} quality findings
                  </summary>
                  <ul>
                    {ex.manifest.qa.warnings.map((warning, i) => (
                      <li key={i}>{warning}</li>
                    ))}
                  </ul>
                </details>
              )}
              <details>
                <summary>Effective image resolution</summary>
                <pre>
                  {JSON.stringify(ex.manifest.qa.effective_dpi, null, 2)}
                </pre>
              </details>
            </section>
          ))}
        </div>
      )}
      <UsagePanel book={book} run={run} />
    </>
  );
}
function UsagePanel({ book, run }: { book: Book; run: Run }) {
  const [budget, setBudget] = useState(book.budget_usd);
  return (
    <section className="panel usage-panel">
      <div className="section-heading">
        <div>
          <h3>Creative control includes cost control.</h3>
          <p>
            Configured-rate accounting, including conservative image ceilings.
            Reconcile with provider billing.
          </p>
        </div>
        <strong>
          {money(book.metrics.spent_and_reserved_usd)}{" "}
          <span className="muted">/ {money(book.budget_usd)}</span>
        </strong>
      </div>
      <div className="inline-form">
        <Field label="Budget cap (USD)">
          <input
            type="number"
            value={budget}
            min={0.1}
            max={10000}
            onChange={(e) => setBudget(Number(e.target.value))}
          />
        </Field>
        <Button
          variant="outline small"
          onClick={() =>
            run(
              () =>
                api(`/projects/${book.id}/budget`, {
                  method: "PATCH",
                  body: JSON.stringify({ budget_usd: budget }),
                }),
              "Budget updated.",
            )
          }
        >
          Update cap
        </Button>
      </div>
      {book.usage.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Operation</th>
                <th>Model</th>
                <th>Usage</th>
                <th>Status</th>
                <th>Cost / reserve</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {book.usage.map((u) => (
                <tr key={u.id}>
                  <td>{u.kind}</td>
                  <td>{u.model}</td>
                  <td>
                    {u.image_calls
                      ? `${u.image_calls} image`
                      : `${u.input_tokens + u.output_tokens} tokens`}
                  </td>
                  <td>{u.status}</td>
                  <td>{money(u.cost_usd)}</td>
                  <td>
                    {u.status === "reserved" && (
                      <button
                        className="text-button"
                        onClick={() => {
                          const charged = window.confirm(
                            "Check this request in provider billing first. Was it charged? OK = charged, Cancel = not charged.",
                          );
                          if (
                            window.confirm(
                              "Reconcile this request? Retrying may incur a new charge.",
                            )
                          )
                            run(
                              () =>
                                api(
                                  `/projects/${book.id}/usage/${u.id}/resolve`,
                                  post({
                                    charged,
                                    confirm_retry_may_charge_again: true,
                                  }),
                                ),
                              "Usage reconciled.",
                            );
                        }}
                      >
                        Reconcile
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
function Settings({ system }: { system: SystemSettings | null }) {
  return (
    <>
      <div className="page-heading">
        <div className="eyebrow">YOUR STUDIO, YOUR TERMS</div>
        <h1>
          Studio settings<span className="accent">.</span>
        </h1>
        <p>The tools behind your next edition.</p>
      </div>
      <div className="settings-grid">
        <section className="panel">
          <div className="panel-heading">
            <h2>Generation provider</h2>
            <p>
              Credentials stay on the server. They are never sent to this
              browser.
            </p>
          </div>
          <dl className="settings-list">
            <div>
              <dt>Studio mode</dt>
              <dd>
                <Badge tone={system?.ai_mode === "live" ? "green" : "amber"}>
                  {system?.ai_mode}
                </Badge>
              </dd>
            </div>
            <div>
              <dt>Text model</dt>
              <dd>{system?.text_model}</dd>
            </div>
            <div>
              <dt>Image model</dt>
              <dd>{system?.image_model}</dd>
            </div>
            <div>
              <dt>Economy image model</dt>
              <dd>{system?.economy_image_model}</dd>
            </div>
            <div>
              <dt>Server API key</dt>
              <dd>
                {system?.api_key_configured ? "Configured" : "Not configured"}
              </dd>
            </div>
            <div>
              <dt>Pricing confirmed</dt>
              <dd>{system?.pricing_confirmed ? "Yes" : "No"}</dd>
            </div>
            <div>
              <dt>Preview image ceiling</dt>
              <dd>{money(system?.preview_image_ceiling)}</dd>
            </div>
            <div>
              <dt>Final image ceiling</dt>
              <dd>{money(system?.final_image_ceiling)}</dd>
            </div>
          </dl>
        </section>
        <section className="panel">
          <h2>Prepare the live studio.</h2>
          <p className="muted">
            In the server environment settings, set AI_MODE=live and
            OPENAI_API_KEY. Verify current text rates and conservative
            image-cost ceilings, then set PRICING_CONFIRMED=true and restart the
            API and worker.
          </p>
          <div className="info-box">
            <LockKeyhole size={20} />
            <p>
              Image calls include reference inputs. Budget ceilings must cover
              the full request, including those references. Never enter API
              credentials into a manuscript, prompt, or browser field.
            </p>
          </div>
          <dl className="settings-list">
            <div>
              <dt>Object storage</dt>
              <dd>{system?.storage}</dd>
            </div>
            <div>
              <dt>Durable job queue</dt>
              <dd>{system?.queue}</dd>
            </div>
            <div>
              <dt>Real API smoke test</dt>
              <dd>Explicit opt-in only</dd>
            </div>
          </dl>
        </section>
      </div>
    </>
  );
}
