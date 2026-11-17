from pathlib import Path

path = Path("collectors/iasc_horizon.py")
text = path.read_text(encoding="utf-8-sig")

start = text.find("def extract_profile_badges(")
end = text.find("\ndef ", start + 10)

if start < 0 or end < 0:
    raise RuntimeError(
        "Could not locate extract_profile_badges()."
    )

new_function = r'''
def extract_profile_badges(
    pdf_path,
    page_number,
):
    """
    Dynamically extract profile Impact and Likelihood badges.

    The brief renders the badges graphically, and the Likelihood badge
    may be rotated or separated from its label. This parser therefore:

      1. renders the page at high resolution;
      2. examines the upper badge band;
      3. OCRs overlapping horizontal regions;
      4. tries 0, 90 and 270 degree rotations;
      5. tries grayscale and high-contrast binary images;
      6. maps Impact and Likelihood with separate vocabularies.

    No country score is hard-coded.
    """

    try:
        import pymupdf
        import pytesseract

        from PIL import (
            Image,
            ImageOps,
            ImageEnhance,
        )

    except ImportError as exc:

        raise RuntimeError(
            "Profile OCR requires pymupdf, "
            "pytesseract and pillow."
        ) from exc

    tesseract_candidates = [
        Path.home()
        / "AppData"
        / "Local"
        / "Programs"
        / "Tesseract-OCR"
        / "tesseract.exe",

        Path(
            r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        ),
    ]

    for candidate in tesseract_candidates:

        if candidate.exists():

            pytesseract.pytesseract.tesseract_cmd = str(
                candidate
            )

            break

    document = pymupdf.open(
        str(pdf_path)
    )

    page = document[
        page_number - 1
    ]

    pix = page.get_pixmap(
        matrix=pymupdf.Matrix(
            6,
            6,
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

    #
    # Badge information is concentrated in the upper section.
    # Use overlapping regions because the two badges can appear
    # at opposite sides of the profile heading.
    #
    regions = [
        (
            "upper-full",
            image.crop(
                (
                    0,
                    0,
                    width,
                    int(height * 0.30),
                )
            ),
        ),
        (
            "upper-left",
            image.crop(
                (
                    0,
                    0,
                    int(width * 0.40),
                    int(height * 0.30),
                )
            ),
        ),
        (
            "upper-middle-left",
            image.crop(
                (
                    int(width * 0.15),
                    0,
                    int(width * 0.60),
                    int(height * 0.30),
                )
            ),
        ),
        (
            "upper-middle-right",
            image.crop(
                (
                    int(width * 0.40),
                    0,
                    int(width * 0.85),
                    int(height * 0.30),
                )
            ),
        ),
        (
            "upper-right",
            image.crop(
                (
                    int(width * 0.65),
                    0,
                    width,
                    int(height * 0.30),
                )
            ),
        ),
    ]

    impact_levels = {
        "very high": 5,
        "high": 4,
        "moderate": 3,
        "low": 2,
        "very low": 1,
    }

    likelihood_levels = {
        "very likely": 5,
        "likely": 4,
        "possible": 3,
        "unlikely": 2,
        "very unlikely": 1,
    }

    impact = None
    likelihood = None
    evidence_parts = []

    def normalize_ocr(value):

        value = str(value).lower()

        value = value.replace(
            "\n",
            " ",
        )

        value = value.replace(
            "|",
            "i",
        )

        value = value.replace(
            "1ikely",
            "likely",
        )

        value = value.replace(
            "l ikely",
            "likely",
        )

        return re.sub(
            r"\s+",
            " ",
            value,
        ).strip()

    def detect_levels(value):

        normalized = normalize_ocr(
            value
        )

        found_impact = None
        found_likelihood = None

        #
        # Prefer phrases linked to their dimension label.
        #
        impact_patterns = [
            (
                r"\bvery\s+high\b.{0,80}\bimpact\b"
                r"|\bimpact\b.{0,80}\bvery\s+high\b",
                5,
            ),
            (
                r"\bhigh\b.{0,80}\bimpact\b"
                r"|\bimpact\b.{0,80}\bhigh\b",
                4,
            ),
            (
                r"\bmoderate\b.{0,80}\bimpact\b"
                r"|\bimpact\b.{0,80}\bmoderate\b",
                3,
            ),
            (
                r"\blow\b.{0,80}\bimpact\b"
                r"|\bimpact\b.{0,80}\blow\b",
                2,
            ),
            (
                r"\bvery\s+low\b.{0,80}\bimpact\b"
                r"|\bimpact\b.{0,80}\bvery\s+low\b",
                1,
            ),
        ]

        likelihood_patterns = [
            (
                r"\bvery\s+likely\b.{0,80}\blikelihood\b"
                r"|\blikelihood\b.{0,80}\bvery\s+likely\b",
                5,
            ),
            (
                r"\blikely\b.{0,80}\blikelihood\b"
                r"|\blikelihood\b.{0,80}\blikely\b",
                4,
            ),
            (
                r"\bpossible\b.{0,80}\blikelihood\b"
                r"|\blikelihood\b.{0,80}\bpossible\b",
                3,
            ),
            (
                r"\bunlikely\b.{0,80}\blikelihood\b"
                r"|\blikelihood\b.{0,80}\bunlikely\b",
                2,
            ),
            (
                r"\bvery\s+unlikely\b.{0,80}\blikelihood\b"
                r"|\blikelihood\b.{0,80}\bvery\s+unlikely\b",
                1,
            ),
        ]

        for pattern, level in impact_patterns:

            if re.search(
                pattern,
                normalized,
                flags=re.IGNORECASE,
            ):

                found_impact = level
                break

        for pattern, level in likelihood_patterns:

            if re.search(
                pattern,
                normalized,
                flags=re.IGNORECASE,
            ):

                found_likelihood = level
                break

        #
        # The badge value and dimension label can be separated
        # during OCR. Accept free likelihood vocabulary because
        # words such as "Very Likely" are unique to that scale.
        #
        if found_likelihood is None:

            for label, level in likelihood_levels.items():

                if re.search(
                    r"\b"
                    + re.escape(label)
                    + r"\b",
                    normalized,
                    flags=re.IGNORECASE,
                ):

                    found_likelihood = level
                    break

        #
        # Accept free Impact wording only when Impact is also visible
        # in the same region.
        #
        if (
            found_impact is None
            and
            re.search(
                r"\bimpact\b",
                normalized,
                flags=re.IGNORECASE,
            )
        ):

            for label, level in impact_levels.items():

                if re.search(
                    r"\b"
                    + re.escape(label)
                    + r"\b",
                    normalized,
                    flags=re.IGNORECASE,
                ):

                    found_impact = level
                    break

        return (
            found_impact,
            found_likelihood,
        )

    for region_name, region in regions:

        if (
            impact is not None
            and
            likelihood is not None
        ):
            break

        gray = ImageOps.grayscale(
            region
        )

        gray = ImageEnhance.Contrast(
            gray
        ).enhance(
            2.8
        )

        binary = gray.point(
            lambda value:
                255
                if value > 165
                else 0
        )

        variants = [
            (
                "gray",
                gray,
            ),
            (
                "binary",
                binary,
            ),
        ]

        for variant_name, variant in variants:

            for rotation in [
                0,
                90,
                270,
            ]:

                rotated = (
                    variant
                    if rotation == 0
                    else variant.rotate(
                        rotation,
                        expand=True,
                    )
                )

                for psm in [
                    6,
                    11,
                    12,
                ]:

                    ocr_text = (
                        pytesseract
                        .image_to_string(
                            rotated,
                            config=f"--psm {psm}",
                        )
                    )

                    evidence_parts.append(
                        (
                            f"[{region_name}; "
                            f"{variant_name}; "
                            f"rotation={rotation}; "
                            f"psm={psm}]\n"
                            f"{ocr_text}"
                        )
                    )

                    (
                        detected_impact,
                        detected_likelihood,
                    ) = detect_levels(
                        ocr_text
                    )

                    if (
                        impact is None
                        and
                        detected_impact is not None
                    ):

                        impact = (
                            detected_impact
                        )

                    if (
                        likelihood is None
                        and
                        detected_likelihood
                        is not None
                    ):

                        likelihood = (
                            detected_likelihood
                        )

                    if (
                        impact is not None
                        and
                        likelihood is not None
                    ):
                        break

                if (
                    impact is not None
                    and
                    likelihood is not None
                ):
                    break

            if (
                impact is not None
                and
                likelihood is not None
            ):
                break

    evidence = (
        "\n\n--- OCR PASS ---\n\n"
        .join(
            evidence_parts
        )
    )

    return (
        impact,
        likelihood,
        evidence,
    )

'''

updated = (
    text[:start]
    + new_function
    + text[end:]
)

compile(
    updated,
    str(path),
    "exec",
)

path.write_text(
    updated,
    encoding="utf-8",
)

print(
    "SUCCESS: multi-region, rotated profile OCR installed."
)
