"""
Утилита для очистки базы от битых записей и файлов-сирот.

Примеры:
    python tools/cleanup_db.py --stats
    python tools/cleanup_db.py --dry-run --delete-broken
    python tools/cleanup_db.py --delete-broken
    python tools/cleanup_db.py --dedupe
    python tools/cleanup_db.py --delete-orphans
    python tools/cleanup_db.py --reset-failed
    python tools/cleanup_db.py --nuke-downloads
"""

import argparse
import logging
import sqlite3
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / 'data'
DB_PATH = DATA_DIR / 'tracks.db'
DOWNLOADS_DIR = DATA_DIR / 'downloads'
COVERS_DIR = DATA_DIR / 'covers'


logging.basicConfig(level=logging.INFO, format='%(message)s')
log = logging.getLogger('cleanup')


def open_db() -> sqlite3.Connection:
    if not DB_PATH.exists():
        log.error(f"База не найдена: {DB_PATH}")
        sys.exit(1)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def resolve_path(rel_path: str | None) -> Path | None:
    """Относительный путь из базы → абсолютный."""
    if not rel_path:
        return None
    p = Path(rel_path)
    if not p.is_absolute():
        p = DATA_DIR / p
    return p


def print_stats(conn: sqlite3.Connection) -> None:
    """Показывает статистику базы."""
    total = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
    log.info(f"Всего треков в базе: {total}")
    log.info("")
    log.info("По статусам:")
    for row in conn.execute(
        "SELECT download_status, COUNT(*) FROM tracks GROUP BY download_status"
    ):
        log.info(f"  {row[0]:15} {row[1]}")

    # Битые done
    broken = find_broken(conn)
    log.info("")
    log.info(f"Битых записей (файл отсутствует): {len(broken)}")

    # Дубли по video_id
    dupes = conn.execute("""
        SELECT video_id, COUNT(*) AS n
        FROM tracks
        GROUP BY video_id
        HAVING n > 1
    """).fetchall()
    log.info(f"Дублей по video_id: {len(dupes)}")

    # Файлы-сироты
    if DOWNLOADS_DIR.exists():
        known = {r[0] for r in conn.execute("SELECT video_id FROM tracks").fetchall()}
        orphans = [f for f in DOWNLOADS_DIR.glob('*.mp3') if f.stem not in known]
        log.info(f"Файлов-сирот в downloads/: {len(orphans)}")


def find_broken(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Записи, у которых файл отсутствует."""
    rows = conn.execute(
        "SELECT id, video_id, title, download_status, file_path FROM tracks"
    ).fetchall()

    broken = []
    for r in rows:
        if r['download_status'] not in ('done', 'failed'):
            continue
        path = resolve_path(r['file_path'])
        if path is None or not path.exists():
            broken.append(r)
    return broken


def find_duplicates(conn: sqlite3.Connection) -> list[tuple[str, list[sqlite3.Row]]]:
    """Группы дублей по video_id."""
    dupes = conn.execute("""
        SELECT video_id FROM tracks
        GROUP BY video_id HAVING COUNT(*) > 1
    """).fetchall()

    result = []
    for d in dupes:
        vid = d['video_id']
        rows = conn.execute(
            "SELECT * FROM tracks WHERE video_id = ? ORDER BY id",
            (vid,),
        ).fetchall()
        result.append((vid, rows))
    return result


def delete_broken(conn: sqlite3.Connection, rows: list[sqlite3.Row], dry_run: bool) -> None:
    if not rows:
        log.info("Битых записей нет")
        return
    if dry_run:
        log.info(f"[DRY-RUN] Будет удалено {len(rows)} записей:")
        for r in rows[:20]:
            log.info(f"  id={r['id']}  [{r['download_status']}]  {r['title'][:60]}")
        return

    ids = [r['id'] for r in rows]
    conn.executemany("DELETE FROM tracks WHERE id = ?", [(i,) for i in ids])
    conn.commit()
    log.info(f"Удалено записей: {len(ids)}")


def dedupe(conn: sqlite3.Connection, dry_run: bool) -> None:
    """Удаляет дубли по video_id, оставляя самый старый id."""
    dupes = find_duplicates(conn)
    if not dupes:
        log.info("Дублей нет")
        return

    to_delete = []
    for vid, rows in dupes:
        # Оставляем первый (самый старый id), остальные на удаление
        for r in rows[1:]:
            to_delete.append(r['id'])

    if dry_run:
        log.info(f"[DRY-RUN] Будет удалено {len(to_delete)} дублей")
        for vid, rows in dupes[:10]:
            log.info(f"  video_id={vid}  ({len(rows)} записей)")
        return

    conn.executemany("DELETE FROM tracks WHERE id = ?", [(i,) for i in to_delete])
    conn.commit()
    log.info(f"Удалено дублей: {len(to_delete)}")


def reset_failed(conn: sqlite3.Connection, dry_run: bool) -> None:
    """Сбрасывает failed → pending, чтобы попробовать скачать заново."""
    count = conn.execute(
        "SELECT COUNT(*) FROM tracks WHERE download_status = 'failed'"
    ).fetchone()[0]

    if count == 0:
        log.info("Нет записей со статусом failed")
        return

    if dry_run:
        log.info(f"[DRY-RUN] Будет сброшено в pending: {count} записей")
        return

    conn.execute("""
        UPDATE tracks
        SET download_status = 'pending', file_path = NULL
        WHERE download_status = 'failed'
    """)
    conn.commit()
    log.info(f"Сброшено в pending: {count}")


def delete_orphans(conn: sqlite3.Connection, dry_run: bool) -> None:
    """Удаляет MP3 в downloads/, которых нет в базе."""
    if not DOWNLOADS_DIR.exists():
        log.info("Папка downloads/ не существует")
        return

    known = {r[0] for r in conn.execute("SELECT video_id FROM tracks").fetchall()}
    orphans = [f for f in DOWNLOADS_DIR.glob('*.mp3') if f.stem not in known]

    if not orphans:
        log.info("Файлов-сирот нет")
        return

    if dry_run:
        log.info(f"[DRY-RUN] Будет удалено {len(orphans)} файлов:")
        for f in orphans[:20]:
            log.info(f"  {f.name}")
        return

    removed = 0
    for f in orphans:
        try:
            f.unlink()
            removed += 1
        except OSError as e:
            log.warning(f"Не удалось удалить {f.name}: {e}")
    log.info(f"Удалено файлов: {removed}")


def nuke_downloads(conn: sqlite3.Connection, dry_run: bool) -> None:
    """
    Полный сброс:
    - Удаляет все MP3 и обложки.
    - Обнуляет file_path, cover_path у всех треков.
    - Сбрасывает done и failed в pending.
    Использовать, если хотите перекачать всю библиотеку с нуля.
    """
    if dry_run:
        count = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
        files = list(DOWNLOADS_DIR.glob('*.mp3')) if DOWNLOADS_DIR.exists() else []
        covers = list(COVERS_DIR.glob('*.jpg')) if COVERS_DIR.exists() else []
        log.info(f"[DRY-RUN] Будет удалено: {len(files)} MP3, {len(covers)} обложек")
        log.info(f"[DRY-RUN] Будет сброшено в pending: {count} треков")
        return

    # Удаляем файлы
    for folder in (DOWNLOADS_DIR, COVERS_DIR):
        if folder.exists():
            for f in folder.glob('*'):
                if f.is_file():
                    try:
                        f.unlink()
                    except OSError:
                        pass

    # Сброс БД
    conn.execute("""
        UPDATE tracks
        SET download_status = 'pending',
            file_path = NULL,
            cover_path = NULL
    """)
    conn.commit()
    log.info("Библиотека полностью сброшена в pending")


def main() -> None:
    parser = argparse.ArgumentParser(description="Очистка базы YT Music Local")
    parser.add_argument('--stats', action='store_true', help='Показать статистику')
    parser.add_argument('--delete-broken', action='store_true', help='Удалить битые записи')
    parser.add_argument('--dedupe', action='store_true', help='Удалить дубли по video_id')
    parser.add_argument('--reset-failed', action='store_true', help='Сбросить failed → pending')
    parser.add_argument('--delete-orphans', action='store_true', help='Удалить MP3-сироты')
    parser.add_argument('--nuke-downloads', action='store_true', help='Полный сброс библиотеки')
    parser.add_argument('--dry-run', action='store_true', help='Только показать, не менять')
    parser.add_argument('--all', action='store_true', help='Выполнить всё (кроме nuke)')

    args = parser.parse_args()

    if not any([
        args.stats, args.delete_broken, args.dedupe, args.reset_failed,
        args.delete_orphans, args.nuke_downloads, args.all
    ]):
        parser.print_help()
        return

    conn = open_db()

    if args.stats or args.all:
        print_stats(conn)
        print()

    if args.delete_broken or args.all:
        broken = find_broken(conn)
        delete_broken(conn, broken, args.dry_run)
        print()

    if args.dedupe or args.all:
        dedupe(conn, args.dry_run)
        print()

    if args.reset_failed or args.all:
        reset_failed(conn, args.dry_run)
        print()

    if args.delete_orphans or args.all:
        delete_orphans(conn, args.dry_run)
        print()

    if args.nuke_downloads:
        nuke_downloads(conn, args.dry_run)

    conn.close()


if __name__ == '__main__':
    main()