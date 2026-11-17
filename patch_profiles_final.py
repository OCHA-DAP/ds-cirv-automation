from pathlib import Path

path = Path("collectors/iasc_horizon.py")
text = path.read_text(encoding="utf-8-sig")

start = text.find("def ocr_page(")
end = text.find("def consolidate_country(", start)

if start < 0:
    raise RuntimeError("Could not find def ocr_page(")

if end < 0:
    raise RuntimeError("Could not find def consolidate_country(")

replacement = r'''
def _setup_tesseract():
    import pytesseract

    candidates = [
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

    for candidate in candidates:
        if candidate.exists():
            pytesseract.pytesseract.tesseract_cmd = str(candidate)
            return

    raise RuntimeError(
        "Tesseract executable could not be found."
    )


def _clean_badge_text(value):
    value = str(value).upper()

    replacements = {
        "H1GH": "HIGH",
        "HICH": "HIGH",
        "HIGI": "HIGH",
        "L0W": "LOW",
        "LOVV": "LOW",
        "VERV": "VERY",
        "VFRY": "VERY",
        "1IKELY": "LIKELY",
        "L1KELY": "LIKELY",
        "LIKEIY": "LIKELY",
        "LIKELV": "LIKELY",
        "|": "I",
    }

    for old, new in replacements.items():
        value = value.replace(old, new)

    value = re.sub(
        r"[^A-Z ]+",
        " ",
        value,
    )

    return re.sub(
        r"\s+",
        " ",
        value,
    ).strip()


def _badge_level(value):
    """
    Convert the profile badge value to level 1-5.

    The graphical badges use seriousness-style labels:
        Very Low
        Low
        Moderate
        High
        Very High
    """

    value = _clean_badge_text(value)

    mappings = [
        ("VERY HIGH", 5),
        ("MODERATE", 3),
        ("VERY LOW", 1),
        ("HIGH", 4),
        ("LOW", 2),
    ]

    for label, level in mappings:
        if re.search(
            r"\b" + re.escape(label) + r"\b",
            value,
        ):
            return level, label

    return None, None


def _calibrate_profile_badges(document):
    """
    Use Myanmar page 5 to determine the exact positions of the
    Likelihood and Impact badge VALUES.

    Myanmar exposes both values in the PDF text layer:

        HIGH
        LOW
        Myanmar
        LIKELIHOOD
        IMPACT

    Therefore:
        HIGH = Likelihood badge
        LOW  = Impact badge

    Coordinates are stored proportionally so the same locations
    can be reused on Yemen and South Sudan.
    """

    page = document[4]

    words = page.get_text(
        "words",
        sort=True,
    )

    page_width = page.rect.width
    page_height = page.rect.height

    severity_words = []

    for word in words:
        x0, y0, x1, y1, value = word[:5]

        cleaned = _clean_badge_text(value)

        level, label = _badge_level(cleaned)

        if (
            level is not None
            and
            y0 < page_height * 0.25
        ):
            severity_words.append(
                {
                    "x0": x0,
                    "y0": y0,
                    "x1": x1,
                    "y1": y1,
                    "level": level,
                    "label": label,
                }
            )

    #
    # If PyMuPDF split VERY HIGH into separate words this does not
    # affect calibration on Myanmar because values are HIGH and LOW.
    #
    high_candidates = [
        item
        for item in severity_words
        if item["label"] == "HIGH"
    ]

    low_candidates = [
        item
        for item in severity_words
        if item["label"] == "LOW"
    ]

    if not high_candidates or not low_candidates:
        raise RuntimeError(
            "Could not calibrate profile badge locations from "
            "Myanmar page 5."
        )

    #
    # Use the uppermost HIGH and LOW values.
    #
    likelihood_word = sorted(
        high_candidates,
        key=lambda item: item["y0"],
    )[0]

    impact_word = sorted(
        low_candidates,
        key=lambda item: item["y0"],
    )[0]

    def make_rect(item):
        center_x = (
            item["x0"] + item["x1"]
        ) / 2.0

        center_y = (
            item["y0"] + item["y1"]
        ) / 2.0

        #
        # Generous crop around each badge value.
        #
        left = max(
            0,
            center_x - 70,
        )

        right = min(
            page_width,
            center_x + 70,
        )

        top = max(
            0,
            center_y - 45,
        )

        bottom = min(
            page_height,
            center_y + 45,
        )

        return {
            "left": left / page_width,
            "right": right / page_width,
            "top": top / page_height,
            "bottom": bottom / page_height,
        }

    likelihood_rect = make_rect(
        likelihood_word
    )

    impact_rect = make_rect(
        impact_word
    )

    print(
        "Profile badge locations calibrated from Myanmar page 5."
    )

    return {
        "likelihood": likelihood_rect,
        "impact": impact_rect,
    }


def _ocr_profile_badge(
    image,
    rect,
):
    """
    OCR exactly one badge value.

    Tries grayscale, inversion, HSV-derived channels and several
    threshold values. Returns the first recognized 1-5 category.
    """

    import cv2
    import numpy as np
    import pytesseract

    from PIL import Image

    width, height = image.size

    left = int(
        rect["left"] * width
    )

    top = int(
        rect["top"] * height
    )

    right = int(
        rect["right"] * width
    )

    bottom = int(
        rect["bottom"] * height
    )

    crop = image.crop(
        (
            left,
            top,
            right,
            bottom,
        )
    )

    rgb = np.array(crop)

    gray = cv2.cvtColor(
        rgb,
        cv2.COLOR_RGB2GRAY,
    )

    gray = cv2.resize(
        gray,
        None,
        fx=4.0,
        fy=4.0,
        interpolation=cv2.INTER_CUBIC,
    )

    #
    # Extract separate RGB channels because colored badge text
    # may disappear during ordinary grayscale conversion.
    #
    r, g, b = cv2.split(
        cv2.cvtColor(
            rgb,
            cv2.COLOR_RGB2BGR,
        )
    )

    channels = []

    for channel in [r, g, b]:
        channels.append(
            cv2.resize(
                channel,
                None,
                fx=4.0,
                fy=4.0,
                interpolation=cv2.INTER_CUBIC,
            )
        )

    variants = [
        ("gray", gray),
        (
            "inverted",
            cv2.bitwise_not(gray),
        ),
        ("channel-r", channels[0]),
        ("channel-g", channels[1]),
        ("channel-b", channels[2]),
    ]

    evidence = []

    for variant_name, variant in variants:

        processing = [
            (
                "original",
                variant,
            )
        ]

        #
        # Otsu threshold.
        #
        _, otsu = cv2.threshold(
            variant,
            0,
            255,
            cv2.THRESH_BINARY
            + cv2.THRESH_OTSU,
        )

        processing.append(
            (
                "otsu",
                otsu,
            )
        )

        processing.append(
            (
                "otsu-inverted",
                cv2.bitwise_not(otsu),
            )
        )

        for threshold in [
            90,
            120,
            150,
            180,
            210,
        ]:

            _, binary = cv2.threshold(
                variant,
                threshold,
                255,
                cv2.THRESH_BINARY,
            )

            processing.append(
                (
                    f"threshold-{threshold}",
                    binary,
                )
            )

        for processing_name, processed in processing:

            pil_image = Image.fromarray(
                processed
            )

            for psm in [
                6,
                7,
                11,
                13,
            ]:

                result = (
                    pytesseract
                    .image_to_string(
                        pil_image,
                        config=(
                            f"--psm {psm} "
                            "-c tessedit_char_whitelist="
                            "ABCDEFGHIJKLMNOPQRSTUVWXYZ "
                        ),
                    )
                )

                cleaned = _clean_badge_text(
                    result
                )

                if not cleaned:
                    continue

                evidence.append(
                    (
                        f"{variant_name}/"
                        f"{processing_name}/"
                        f"psm={psm}: "
                        f"{cleaned}"
                    )
                )

                level, label = _badge_level(
                    cleaned
                )

                if level is not None:

                    return (
                        level,
                        label,
                        evidence,
                    )

    return (
        None,
        None,
        evidence,
    )


def extract_high_concern(
    pages,
    pdf_path,
    alias_lookup,
    source_file,
):
    """
    Parse all High Concern profiles.

    Badge positions are calibrated from Myanmar and applied to every
    profile page. The extracted Impact and Likelihood levels are then
    converted using the existing methodology matrix.
    """

    import pymupdf

    from PIL import Image

    _setup_tesseract()

    profiles = [
        (
            3,
            "Yemen",
        ),
        (
            4,
            "South Sudan",
        ),
        (
            5,
            "Myanmar",
        ),
    ]

    records = []
    unmatched = []

    document = pymupdf.open(
        str(pdf_path)
    )

    badge_rects = (
        _calibrate_profile_badges(
            document
        )
    )

    for page_number, label in profiles:

        page = document[
            page_number - 1
        ]

        page_text = pages[
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

        (
            likelihood,
            likelihood_text,
            likelihood_evidence,
        ) = _ocr_profile_badge(
            image,
            badge_rects[
                "likelihood"
            ],
        )

        (
            impact,
            impact_text,
            impact_evidence,
        ) = _ocr_profile_badge(
            image,
            badge_rects[
                "impact"
            ],
        )

        print(
            f"Profile {label}: "
            f"Impact={impact} "
            f"({impact_text}), "
            f"Likelihood={likelihood} "
            f"({likelihood_text})"
        )

        evidence = (
            "LIKELIHOOD BADGE\n"
            +
            "\n".join(
                likelihood_evidence
            )
            +
            "\n\nIMPACT BADGE\n"
            +
            "\n".join(
                impact_evidence
            )
        )

        if (
            impact is None
            or
            likelihood is None
        ):

            unmatched.append(
                {
                    "Source_Label":
                        label,

                    "PDF_Page":
                        page_number,

                    "Reason":
                        (
                            "Could not read both calibrated "
                            "profile badge values. "
                            f"Impact={impact}, "
                            f"Likelihood={likelihood}"
                        ),

                    "Evidence":
                        evidence[:15000],
                }
            )

            continue

        matrix_level = (
            IMPACT_LIKELIHOOD_MATRIX[
                impact
            ][
                likelihood
            ]
        )

        (
            seriousness,
            score,
        ) = MATRIX_LEVEL_TO_RESULT[
            matrix_level
        ]

        iso3_values = map_source_label(
            label,
            alias_lookup,
        )

        if not iso3_values:

            unmatched.append(
                {
                    "Source_Label":
                        label,

                    "PDF_Page":
                        page_number,

                    "Reason":
                        "Profile country could not be mapped",

                    "Evidence":
                        evidence[:15000],
                }
            )

            continue

        normalized_page = normalize_text(
            page_text
        )

        risk_types = []

        for term, canonical in [
            ("conflict", "Conflict"),
            ("violence", "Violence"),
            ("displacement", "Displacement"),
            ("ebola", "Health"),
            ("flood", "Flood"),
            ("food", "Food insecurity"),
        ]:

            if (
                term in normalized_page
                and
                canonical not in risk_types
            ):

                risk_types.append(
                    canonical
                )

        for iso3 in iso3_values:

            records.append(
                {
                    "ISO3":
                        iso3,

                    "Source_Label":
                        label,

                    "IASC_Early_Warning_Matrix_Level":
                        matrix_level,

                    "IASC_Early_Warning_Impact_Level":
                        impact,

                    "IASC_Early_Warning_Likelihood_Level":
                        likelihood,

                    "IASC_Early_Warning_Seriousness":
                        seriousness,

                    "IASC_Early_Warning_Type":
                        (
                            "; ".join(
                                risk_types
                            )
                            if risk_types
                            else pd.NA
                        ),

                    "IASC_Early_Warning_Score":
                        score,

                    "IASC_Scoring_Method":
                        (
                            "Impact x Likelihood matrix from "
                            "template-calibrated profile badges"
                        ),

                    "IASC_Source_Section":
                        "Risks of High Concern",

                    "IASC_PDF_Page":
                        page_number,

                    "IASC_Rating_Evidence":
                        evidence[:15000],

                    "IASC_Source_File":
                        source_file.name,
                }
            )

    return (
        records,
        unmatched,
    )


'''

updated = (
    text[:start]
    + replacement
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
    "SUCCESS: template-calibrated profile parser installed."
)
