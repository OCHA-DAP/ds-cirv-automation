from pathlib import Path

path = Path("collectors/iasc_horizon.py")
text = path.read_text(encoding="utf-8-sig")

start = text.find("def ocr_page(")
end = text.find("def consolidate_country(", start)

if start < 0 or end < 0:
    raise RuntimeError(
        "Could not locate the profile extraction section."
    )

replacement = r'''
def _configure_tesseract():
    """
    Configure Tesseract without relying on the terminal PATH.
    """

    import pytesseract

    candidates = [
        (
            Path.home()
            / "AppData"
            / "Local"
            / "Programs"
            / "Tesseract-OCR"
            / "tesseract.exe"
        ),
        Path(
            r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        ),
    ]

    for candidate in candidates:

        if candidate.exists():

            pytesseract.pytesseract.tesseract_cmd = str(
                candidate
            )

            return

    raise RuntimeError(
        "Tesseract executable was not found."
    )


def _normalize_ocr(value):
    """
    Normalize common OCR mistakes.
    """

    value = str(value).upper()

    replacements = {
        "H1GH": "HIGH",
        "HICH": "HIGH",
        "HIGI": "HIGH",
        "L0W": "LOW",
        "LOVV": "LOW",
        "VERV": "VERY",
        "L1KELY": "LIKELY",
        "1IKELY": "LIKELY",
        "LIKEIY": "LIKELY",
        "LIKELV": "LIKELY",
        "|": "I",
    }

    for old, new in replacements.items():

        value = value.replace(
            old,
            new,
        )

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


def _impact_level(value):
    """
    Convert an Impact badge to level 1-5.
    """

    value = _normalize_ocr(
        value
    )

    mappings = [
        ("VERY HIGH", 5),
        ("MODERATE", 3),
        ("VERY LOW", 1),
        ("HIGH", 4),
        ("LOW", 2),
    ]

    for label, level in mappings:

        if re.search(
            r"\b"
            + re.escape(label)
            + r"\b",
            value,
        ):

            return level

    return None


def _likelihood_level(value):
    """
    Convert a Likelihood badge to level 1-5.
    """

    value = _normalize_ocr(
        value
    )

    mappings = [
        ("VERY UNLIKELY", 1),
        ("VERY LIKELY", 5),
        ("UNLIKELY", 2),
        ("POSSIBLE", 3),
        ("LIKELY", 4),
    ]

    for label, level in mappings:

        if re.search(
            r"\b"
            + re.escape(label)
            + r"\b",
            value,
        ):

            return level

    return None


def _find_template_badge_rectangles(
    document,
    profile_pages,
):
    """
    Find the page coordinates of the LIKELIHOOD and IMPACT labels.

    The function scans the profile pages and uses the first page where
    both labels are available in the native PDF text layer.

    The resulting rectangles are normalized to page width and height,
    so they can be applied to every profile page using the same layout.
    """

    for page_number in profile_pages:

        page = document[
            page_number - 1
        ]

        words = page.get_text(
            "words",
            sort=True,
        )

        likelihood_word = None
        impact_word = None

        for word in words:

            x0, y0, x1, y1, value = word[:5]

            normalized = _normalize_ocr(
                value
            )

            if "LIKELIHOOD" in normalized:

                likelihood_word = (
                    x0,
                    y0,
                    x1,
                    y1,
                )

            if normalized == "IMPACT":

                impact_word = (
                    x0,
                    y0,
                    x1,
                    y1,
                )

        if (
            likelihood_word is None
            or
            impact_word is None
        ):
            continue

        page_width = page.rect.width
        page_height = page.rect.height

        def badge_rectangle(
            word_box,
        ):

            x0, y0, x1, y1 = word_box

            center_x = (
                x0 + x1
            ) / 2.0

            #
            # Capture a generous area above and around the dimension
            # label. This contains the graphical badge value.
            #
            left = max(
                0,
                center_x - 95,
            )

            right = min(
                page_width,
                center_x + 95,
            )

            top = max(
                0,
                y0 - 125,
            )

            bottom = min(
                page_height,
                y1 + 20,
            )

            return {
                "left":
                    left / page_width,

                "top":
                    top / page_height,

                "right":
                    right / page_width,

                "bottom":
                    bottom / page_height,
            }

        return {
            "likelihood":
                badge_rectangle(
                    likelihood_word
                ),

            "impact":
                badge_rectangle(
                    impact_word
                ),

            "calibration_page":
                page_number,
        }

    raise RuntimeError(
        "Could not calibrate profile badge positions "
        "from any High Concern profile page."
    )


def _ocr_badge_crop(
    image,
    normalized_rectangle,
    dimension,
):
    """
    OCR one calibrated badge crop using several lightweight
    transformations.
    """

    import cv2
    import numpy as np
    import pytesseract

    from PIL import Image

    width, height = image.size

    left = int(
        width
        *
        normalized_rectangle[
            "left"
        ]
    )

    top = int(
        height
        *
        normalized_rectangle[
            "top"
        ]
    )

    right = int(
        width
        *
        normalized_rectangle[
            "right"
        ]
    )

    bottom = int(
        height
        *
        normalized_rectangle[
            "bottom"
        ]
    )

    crop = image.crop(
        (
            left,
            top,
            right,
            bottom,
        )
    )

    rgb = np.array(
        crop
    )

    gray = cv2.cvtColor(
        rgb,
        cv2.COLOR_RGB2GRAY,
    )

    gray = cv2.resize(
        gray,
        None,
        fx=3.0,
        fy=3.0,
        interpolation=cv2.INTER_CUBIC,
    )

    red, green, blue = cv2.split(
        cv2.cvtColor(
            rgb,
            cv2.COLOR_RGB2BGR,
        )
    )

    channel_images = []

    for channel in [
        red,
        green,
        blue,
    ]:

        channel_images.append(
            cv2.resize(
                channel,
                None,
                fx=3.0,
                fy=3.0,
                interpolation=cv2.INTER_CUBIC,
            )
        )

    variants = [
        (
            "gray",
            gray,
        ),
        (
            "inverted",
            cv2.bitwise_not(
                gray
            ),
        ),
        (
            "red",
            channel_images[0],
        ),
        (
            "green",
            channel_images[1],
        ),
        (
            "blue",
            channel_images[2],
        ),
    ]

    evidence = []

    for variant_name, variant in variants:

        processed_versions = [
            (
                "original",
                variant,
            )
        ]

        for threshold in [
            100,
            140,
            180,
            210,
        ]:

            _, binary = cv2.threshold(
                variant,
                threshold,
                255,
                cv2.THRESH_BINARY,
            )

            processed_versions.append(
                (
                    f"threshold-{threshold}",
                    binary,
                )
            )

        for processing_name, processed in processed_versions:

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

                cleaned = _normalize_ocr(
                    result
                )

                if not cleaned:
                    continue

                evidence.append(
                    (
                        f"{variant_name}; "
                        f"{processing_name}; "
                        f"psm={psm}: "
                        f"{cleaned}"
                    )
                )

                if dimension == "impact":

                    level = _impact_level(
                        cleaned
                    )

                else:

                    level = _likelihood_level(
                        cleaned
                    )

                if level is not None:

                    return (
                        level,
                        cleaned,
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
    Parse High Concern profiles using template-calibrated badge crops.

    Badge locations are learned from the PDF itself and then reused
    across pages with the same profile layout.
    """

    import pymupdf

    from PIL import Image

    _configure_tesseract()

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

    template = (
        _find_template_badge_rectangles(
            document,
            [
                5,
                3,
                4,
            ],
        )
    )

    print(
        "Profile badge template calibrated "
        f"from page {template['calibration_page']}."
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
        ) = _ocr_badge_crop(
            image,
            template[
                "likelihood"
            ],
            "likelihood",
        )

        (
            impact,
            impact_text,
            impact_evidence,
        ) = _ocr_badge_crop(
            image,
            template[
                "impact"
            ],
            "impact",
        )

        evidence = (
            "LIKELIHOOD CROP:\n"
            + "\n".join(
                likelihood_evidence
            )
            + "\n\nIMPACT CROP:\n"
            + "\n".join(
                impact_evidence
            )
        )

        print(
            f"Profile {label}: "
            f"Impact={impact}, "
            f"Likelihood={likelihood}, "
            f"ImpactText={impact_text}, "
            f"LikelihoodText={likelihood_text}"
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
                            "profile badge crops. "
                            f"Impact={impact}, "
                            f"Likelihood={likelihood}"
                        ),

                    "Evidence":
                        evidence[:12000],
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
                        evidence[:12000],
                }
            )

            continue

        normalized_page = normalize_text(
            page_text
        )

        risk_types = []

        for term, canonical in [
            (
                "conflict",
                "Conflict",
            ),
            (
                "violence",
                "Violence",
            ),
            (
                "displacement",
                "Displacement",
            ),
            (
                "ebola",
                "Health",
            ),
            (
                "flood",
                "Flood",
            ),
            (
                "food",
                "Food insecurity",
            ),
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
                            "Impact x Likelihood matrix "
                            "from template-calibrated badge crops"
                        ),

                    "IASC_Source_Section":
                        "Risks of High Concern",

                    "IASC_PDF_Page":
                        page_number,

                    "IASC_Rating_Evidence":
                        evidence[:12000],

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
    "SUCCESS: template-calibrated profile extraction installed."
)
