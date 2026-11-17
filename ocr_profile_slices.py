import pymupdf
import pytesseract

from pathlib import Path
from PIL import Image, ImageOps, ImageEnhance


PDF = Path(
    r"2026 Inter-Agency Early Warning Brief 26102026.pdf"
)

TESSERACT = Path(
    r"C:\Users\MALTWAL1\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"
)

pytesseract.pytesseract.tesseract_cmd = str(
    TESSERACT
)

document = pymupdf.open(
    str(PDF)
)

slices = [
    (0.00, 0.20),
    (0.15, 0.35),
    (0.30, 0.50),
    (0.45, 0.65),
    (0.60, 0.80),
    (0.75, 1.00),
]

for page_number in [3, 4]:

    page = document[
        page_number - 1
    ]

    pix = page.get_pixmap(
        matrix=pymupdf.Matrix(
            5,
            5,
        ),
        alpha=False,
    )

    image = Image.frombytes(
        "RGB",
        [
            pix.width,
            pix.height,
        ],
        pix.samples,
    )

    width, height = image.size

    print()
    print("=" * 70)
    print(
        f"PAGE {page_number}"
    )
    print("=" * 70)

    for index, (
        left,
        right,
    ) in enumerate(
        slices,
        start=1,
    ):

        crop = image.crop(
            (
                int(width * left),
                0,
                int(width * right),
                int(height * 0.35),
            )
        )

        gray = ImageOps.grayscale(
            crop
        )

        gray = ImageEnhance.Contrast(
            gray
        ).enhance(
            2.5
        )

        text = pytesseract.image_to_string(
            gray,
            config="--psm 11",
        )

        print()
        print(
            f"--- SLICE {index} "
            f"({left:.2f}-{right:.2f}) ---"
        )

        print(
            text.strip()
        )
