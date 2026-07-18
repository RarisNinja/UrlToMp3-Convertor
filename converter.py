import shutil
import subprocess
import sys
from pathlib import Path
import yt_dlp

from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, TDRC
from mutagen.id3 import error as ID3Error
from mutagen.mp3 import MP3

try:
    import yt_dlp
    from yt_dlp.utils import sanitize_filename
except ImportError:
    sys.exit("Missing dependency. Install with: pip install yt-dlp mutagen")

try:
    from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, TDRC
    from mutagen.id3 import error as ID3Error
    from mutagen.mp3 import MP3
except ImportError:
    sys.exit("Missing dependency. Install with: pip install yt-dlp mutagen")


def check_ffmpeg():
    if shutil.which("ffmpeg") is None:
        sys.exit("ffmpeg not found")


class UrlToMp3Converter:
    def __init__(self, output_dir="downloads", quality="0", cover_size=720):
        """
        output_dir: where MP3s and cover art get saved.
        quality: '0' (best VBR, ~245-320kbps, default) through '9' (worst),
                 or a constant bitrate string like '320' / '192'.
        cover_size: cover art is center-cropped to a square and resized to
                    cover_size x cover_size. This strips any pillarbox/letterbox
                    bars some source thumbnails have (e.g. a square image padded
                    to 1280x720) and normalizes every cover to the same dimensions.
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.quality = str(quality)
        self.cover_size = int(cover_size)

    # -- internal helpers --------------------------------------------------

    def _progress_hook(self, d):
        if d["status"] == "downloading":
            pct = d.get("_percent_str", "").strip()
            speed = d.get("_speed_str", "").strip()
            print(f"\r  downloading  {pct}  {speed}   ", end="", flush=True)
        elif d["status"] == "finished":
            print("\r  download complete, extracting audio...            ")

    def _find_downloaded_thumbnail(self, base: Path):
        for ext in (".webp", ".jpg", ".jpeg", ".png"):
            p = base.with_suffix(ext)
            if p.exists():
                return p
        return None

    def _make_high_quality_cover(self, src: Path, dst: Path):
        """
        Re-encode the source thumbnail as a high quality, near-lossless JPEG,
        center-cropped to a square (dropping any pillarbox/letterbox bars)
        and resized to self.cover_size x self.cover_size.
        """
        size = self.cover_size
        # min(iw,ih) makes the crop a square that fits inside the source no matter
        # its aspect ratio; the x/y offsets center that square. Commas inside the
        # min(...) calls must be backslash-escaped since ffmpeg's filtergraph syntax
        # otherwise treats a bare comma as "start of the next filter".
        vf = (
            f"crop=min(iw\\,ih):min(iw\\,ih):(iw-min(iw\\,ih))/2:(ih-min(iw\\,ih))/2,"
            f"scale={size}:{size}"
        )
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(src), "-vf", vf, "-qscale:v", "2", str(dst)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _embed_metadata(self, mp3_path: Path, cover_path, info: dict):
        audio = MP3(str(mp3_path), ID3=ID3)
        try:
            audio.add_tags()
        except ID3Error:
            pass
        tags = audio.tags

        if cover_path and Path(cover_path).exists():
            tags.delall("APIC")
            with open(cover_path, "rb") as f:
                tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=f.read()))

        if info.get("title"):
            tags.add(TIT2(encoding=3, text=info["title"]))
        artist = info.get("artist") or info.get("uploader")
        if artist:
            tags.add(TPE1(encoding=3, text=artist))
        if info.get("album"):
            tags.add(TALB(encoding=3, text=info["album"]))
        if info.get("upload_date"):
            tags.add(TDRC(encoding=3, text=info["upload_date"][:4]))

        audio.save(v2_version=3)

    def _unique_path(self, path: Path) -> Path:
        """
        If `path` already exists, append " (1)", " (2)", etc. until we find
        one that's free. Used when consolidating a playlist into one shared
        folder, where two tracks could otherwise sanitize down to the same
        filename.
        """
        if not path.exists():
            return path
        stem, suffix = path.stem, path.suffix
        n = 1
        while True:
            candidate = path.with_name(f"{stem} ({n}){suffix}")
            if not candidate.exists():
                return candidate
            n += 1
    
    def _consolidate_playlist_nested(self, playlist_title: str, song_results: list):
        """
        Regular (non-album) playlist: keep each track in its own subfolder
        (mp3 + its own individual cover), just nested inside one shared
        <output_dir>/<Playlist Title>/ folder instead of scattered loose
        under output_dir. Unlike the album case, nothing gets flattened or
        shares a cover - each song's folder is moved as-is.
        """
        playlist_dir = self.output_dir / sanitize_filename(playlist_title, restricted=False)
        playlist_dir.mkdir(parents=True, exist_ok=True)

        consolidated = []
        for song in song_results:
            song_dir = Path(song["folder"])
            dst_dir = self._unique_path(playlist_dir / song_dir.name)
            shutil.move(str(song_dir), str(dst_dir))

            moved = {"title": song["title"], "folder": str(dst_dir), "mp3": None, "cover": None}
            if song["mp3"]:
                moved["mp3"] = str(dst_dir / Path(song["mp3"]).name)
            if song["cover"]:
                moved["cover"] = str(dst_dir / Path(song["cover"]).name)
            consolidated.append(moved)

        return consolidated

    def _consolidate_playlist(self, playlist_title: str, song_results: list):
        """
        Album only: move every track's mp3 into one shared
        <output_dir>/<Playlist Title>/ folder, since every track shares a
        single album cover. yt-dlp downloads each track into its own
        per-track folder first; those are removed once the mp3 is moved out.
    
        Every entry in song_results points at the same source cover file -
        the shared album cover - so it's moved into place once and every
        track is pointed at that same destination.
        """
        playlist_dir = self.output_dir / sanitize_filename(playlist_title, restricted=False)
        playlist_dir.mkdir(parents=True, exist_ok=True)
    
        shared_cover_dst = None
        consolidated = []
        for song in song_results:
            song_dir = Path(song["folder"])
            moved = {"title": song["title"], "folder": str(playlist_dir), "mp3": None, "cover": None}
    
            if song["mp3"]:
                src = Path(song["mp3"])
                dst = self._unique_path(playlist_dir / src.name)
                shutil.move(str(src), str(dst))
                moved["mp3"] = str(dst)
    
            if song["cover"]:
                if shared_cover_dst is None:
                    src = Path(song["cover"])
                    shared_cover_dst = self._unique_path(playlist_dir / "cover.jpg")
                    if src.exists():
                        shutil.move(str(src), str(shared_cover_dst))
                moved["cover"] = str(shared_cover_dst) if shared_cover_dst.exists() else None
    
            shutil.rmtree(song_dir, ignore_errors=True)
            consolidated.append(moved)
    
        return consolidated

    def _build_album_cover(self, tracks: list):
        """
        Build one cover image to represent the whole album, reused for
        every track, instead of converting each track's own thumbnail
        separately. Real album releases (YouTube Music albums, Bandcamp
        releases, etc.) use identical artwork for every track anyway, so
        the first track with a usable thumbnail stands in for the album's
        cover. Returns the cover Path, or None if no track had a usable
        thumbnail.
        """
        for t in tracks:
            if not t["thumb_path"]:
                continue
            cover_path = t["song_dir"] / "cover.jpg"
            try:
                self._make_high_quality_cover(t["thumb_path"], cover_path)
                return cover_path
            except subprocess.CalledProcessError:
                continue
        return None

    # -- public API -----------------------------------------------------

    def convert(self, url: str):
        """
        Download `url`, convert to MP3, and embed cover art.

        Single track   -> <output_dir>/<Song Title>/<Song Title>.mp3
        Playlist/album -> every track lands together in
                          <output_dir>/<Playlist Title>/<Track Title>.mp3

        Whether `url` is a single track, a playlist, or an album is
        detected automatically from what yt-dlp returns - no flag needed.
        An "album" is a playlist where every track shares the same `album`
        name (yt-dlp's standard metadata field, populated by extractors
        like YouTube Music and Bandcamp for genuine album releases) - as
        opposed to a regular playlist mixing unrelated tracks together.

        Cover art:
        - Single track / regular playlist -> each track keeps its own
          individual cover art (its own video thumbnail).
        - Album -> every track shares one cover (the album art), instead
          of each track's own individual thumbnail.

        Returns a dict (single track) or list of dicts (playlist/album)
        with keys: title, folder, mp3, cover.
        """
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": {
                "default": str(self.output_dir / "%(title)s" / "%(title)s.%(ext)s"),
                "pl_thumbnail": "",  # don't write a playlist/album-level thumbnail
            },
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": self.quality},
            ],
            "writethumbnail": True,
            "noplaylist": False,
            "progress_hooks": [self._progress_hook],
            "quiet": True,
            "no_warnings": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            is_playlist = "entries" in info
            entries = [e for e in (info["entries"] if is_playlist else [info]) if e is not None]

            album_names = [e.get("album") for e in entries]
            is_album = is_playlist and bool(entries) and all(album_names) and len(set(album_names)) == 1

            # Gather the on-disk paths yt-dlp produced for every track first,
            # before touching any cover art or ID3 tags, so we can decide
            # what the album cover should be (if any) up front.
            tracks = []
            for entry in entries:
                original_path = Path(ydl.prepare_filename(entry))
                song_dir = original_path.parent
                tracks.append({
                    "entry": entry,
                    "title": entry.get("title", "audio"),
                    "song_dir": song_dir,
                    "mp3_path": original_path.with_suffix(".mp3"),
                    # Ask yt-dlp for the exact path it used rather than
                    # re-deriving our own - it applies its own filesystem-safe
                    # sanitization, so this stays correct no matter what
                    # characters are in the title.
                    "thumb_path": self._find_downloaded_thumbnail(original_path),
                })

            album_cover_path = self._build_album_cover(tracks) if is_album else None

            results = []
            for t in tracks:
                if is_album:
                    cover_path = album_cover_path
                    if t["thumb_path"]:
                        t["thumb_path"].unlink(missing_ok=True)  # drop the raw intermediate
                else:
                    cover_path = None
                    if t["thumb_path"]:
                        cover_path = t["song_dir"] / "cover.jpg"
                        try:
                            self._make_high_quality_cover(t["thumb_path"], cover_path)
                            t["thumb_path"].unlink(missing_ok=True)  # drop the raw intermediate
                        except subprocess.CalledProcessError:
                            cover_path = None

                if t["mp3_path"].exists():
                    self._embed_metadata(t["mp3_path"], cover_path, t["entry"])

                results.append({
                    "title": t["title"],
                    "folder": str(t["song_dir"]),
                    "mp3": str(t["mp3_path"]) if t["mp3_path"].exists() else None,
                    "cover": str(cover_path) if cover_path and Path(cover_path).exists() else None,
                })

        if is_playlist:
            playlist_title = info.get("title") or "Playlist"
            if is_album:
                return self._consolidate_playlist(playlist_title, results, shared_cover=True)
            return self._consolidate_playlist_nested(playlist_title, results)

        return results[0]