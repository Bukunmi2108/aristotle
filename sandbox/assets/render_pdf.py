from pathlib import Path
import sys
from urllib.parse import unquote, urlparse

from weasyprint import HTML, default_url_fetcher


def main() -> None:
    if len(sys.argv) != 5:
        raise SystemExit("usage: render_pdf.py HTML OUTPUT BASE_DIR WORKSPACE_ROOT")

    html_path = Path(sys.argv[1]).resolve()
    output_path = Path(sys.argv[2]).resolve()
    base_dir = Path(sys.argv[3]).resolve()
    workspace_root = Path(sys.argv[4]).resolve()
    asset_root = Path("/app/assets").resolve()

    def local_only_fetcher(url: str):
        parsed = urlparse(url)
        if parsed.scheme not in {"", "file"}:
            raise ValueError(f"Remote document resource blocked: {parsed.scheme}")
        raw_path = unquote(parsed.path) if parsed.scheme == "file" else unquote(url)
        path = Path(raw_path)
        if not path.is_absolute():
            path = base_dir / path
        resolved = path.resolve()
        if not (
            resolved.is_relative_to(workspace_root)
            or resolved.is_relative_to(asset_root)
        ):
            raise ValueError("Document resource escapes permitted roots.")
        return default_url_fetcher(resolved.as_uri())

    HTML(
        filename=str(html_path),
        base_url=str(base_dir),
        url_fetcher=local_only_fetcher,
    ).write_pdf(str(output_path))


if __name__ == "__main__":
    main()
