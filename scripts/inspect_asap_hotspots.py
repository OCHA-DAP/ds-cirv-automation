from pathlib import Path
import zipfile


project_folder = Path(__file__).parent.parent

zip_path = (
    project_folder
    / "data"
    / "raw"
    / "asap_hotspots"
    / "hotspots_ts.zip"
)


with zipfile.ZipFile(zip_path, "r") as zip_file:

    print("Files inside ASAP ZIP:")
    print("-" * 70)

    for filename in zip_file.namelist():
        print(filename)

    print()
    print("=" * 70)
    print("ASAP README")
    print("=" * 70)

    readme = zip_file.read(
        "readme_hotspots_ts.txt"
    )

    # Try the usual European text encodings
    try:
        readme_text = readme.decode("utf-8")
    except UnicodeDecodeError:
        readme_text = readme.decode(
            "latin-1"
        )

    print(readme_text)

    print()
    print("=" * 70)
    print("FIRST 10 RAW CSV LINES")
    print("=" * 70)

    csv_bytes = zip_file.read(
        "hotspots_ts.csv"
    )

    try:
        csv_text = csv_bytes.decode("utf-8")
    except UnicodeDecodeError:
        csv_text = csv_bytes.decode(
            "latin-1"
        )

    for line in csv_text.splitlines()[:10]:
        print(line)