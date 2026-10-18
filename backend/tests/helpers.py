from hashlib import sha256

from app.models import BookProject, GenerationJob, SourceDocument, User
from app.schemas import ProjectInput
from app.storage import Storage

PASSAGE = (
    "CHAPTER I\n"
    + "Ivanhoe rode toward the castle. Rowena waited by the gate. " * 5
    + "Rebecca cared for Ivanhoe after the tournament. " * 4
)


def make_project(db, pages=2, book_type="illustrated", email="author@example.org"):
    user = User(email=email, password_hash="test-only")
    db.add(user)
    db.flush()
    config = ProjectInput(
        title="Ivanhoe",
        author="Sir Walter Scott",
        rights_confirmed=True,
        rights_declaration="Public domain in my target markets",
        pages_per_chapter=pages,
        book_type=book_type,
    ).model_dump()
    book = BookProject(
        user_id=user.id,
        title="Ivanhoe",
        author="Sir Walter Scott",
        rights_confirmed=True,
        rights_declaration=config["rights_declaration"],
        config=config,
        budget_usd=10,
    )
    db.add(book)
    db.flush()
    raw = PASSAGE.encode()
    key = Storage().put(book.id, raw, "txt", "text/plain")
    db.add(
        SourceDocument(
            project_id=book.id,
            original_author=book.author,
            rights=book.rights_declaration,
            storage_key=key,
            sha256=sha256(raw).hexdigest(),
            char_count=len(PASSAGE),
        )
    )
    job = GenerationJob(project_id=book.id)
    db.add(job)
    db.commit()
    return book, job
