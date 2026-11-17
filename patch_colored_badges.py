from pathlib import Path

path = Path("collectors/iasc_horizon.py")
text = path.read_text(encoding="utf-8-sig")

marker = "def extract_high_concern("

position = text.find(marker)

if position < 0:
    raise RuntimeError(
        "Could not locate extract_high_concern()."
    )

helper = r'''
def extract_colored_profile_badges(
    pdf_path,
    page_number,
):
    """
    Detect and OCR the two colored profile badges independently.

    Profile layout:
        left badge  = Likelihood
        right badge = Impact

    This avoids relying on page-wide OCR reading order.
    """

    import cv2
    import numpy as np
    import pymupdf
    import pytesseract

    from PIL import Image

    tesseract_candidates = [
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
            5,
            5,
        ),
        alpha=False,
    )

    rgb = np.frombuffer(
        pix.samples,
        dtype=np.uint8,
    ).reshape(
        pix.height,
        pix.width,
        3,
    )

    #
    # The badges are located in the upper profile header.
    #
    header_height = int(
        pix.height * 0.22
    )

    header = rgb[
        0:header_height,
        :,
    ]

    hsv = cv2.cvtColor(
        header,
        cv2.COLOR_RGB2HSV,
    )

    #
    # Select saturated colored blocks while excluding ordinary
    # black text and the white page background.
    #
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]

    mask = np.where(
        (saturation > 45)
        &
        (value > 45),
        255,
        0,
    ).astype(
        np.uint8
    )

    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (
            25,
            15,
        ),
    )

    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_CLOSE,
        kernel,
        iterations=2,
    )

    contours, _ = cv2.findContours(
        mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )

    candidates = []

    page_area = (
        header.shape[0]
        *
        header.shape[1]
    )

    for contour in contours:

        x, y, width, height = (
            cv2.boundingRect(
                contour
            )
        )

        area = width * height

        if area < page_area * 0.001:
            continue

        if width < 80 or height < 30:
            continue

        if width > header.shape[1] * 0.60:
            continue

        padding_x = max(
            15,
            int(width * 0.12),
        )

        padding_y = max(
            10,
            int(height * 0.25),
        )

        left = max(
            0,
            x - padding_x,
        )

        top = max(
            0,
            y - padding_y,
        )

        right = min(
            header.shape[1],
            x + width + padding_x,
        )

        bottom = min(
            header.shape[0],
            y + height + padding_y,
        )

        crop = header[
            top:bottom,
            left:right,
        ]

        candidates.append(
            {
                "x":
                    x,

                "y":
                    y,

                "width":
                    width,

                "height":
                    height,

                "crop":
                    crop,
            }
        )

    #
    # The two profile badges should be among the largest colored
    # regions in the header.
    #
    candidates.sort(
        key=lambda item:
            item["width"]
            *
            item["height"],
        reverse=True,
    )

    candidates = candidates[:8]

    severity_map = {
        "VERY HIGH":
            5,

        "HIGH":
            4,

        "MODERATE":
            3,

        "LOW":
            2,

        "VERY LOW":
            1,
    }

    likelihood_map = {
        "VERY LIKELY":
            5,

        "LIKELY":
            4,

        "POSSIBLE":
            3,

        "UNLIKELY":
            2,

        "VERY UNLIKELY":
            1,
    }

    recognized = []

    for candidate in candidates:

        crop_rgb = candidate[
            "crop"
        ]

        crop_bgr = cv2.cvtColor(
            crop_rgb,
            cv2.COLOR_RGB2BGR,
        )

        gray = cv2.cvtColor(
            crop_bgr,
            cv2.COLOR_BGR2GRAY,
        )

        gray = cv2.resize(
            gray,
            None,
            fx=2.5,
            fy=2.5,
            interpolation=cv2.INTER_CUBIC,
        )

        versions = [
            (
                "normal",
                gray,
            ),
            (
                "inverted",
                cv2.bitwise_not(
                    gray
                ),
            ),
        ]

        found_text = None
        found_level = None
        found_dimension = None
        collected_text = []

        for version_name, version in versions:

            for threshold in [
                None,
                100,
                140,
                180,
                210,
            ]:

                if threshold is None:

                    processed = version

                else:

                    _, processed = cv2.threshold(
                        version,
                        threshold,
                        255,
                        cv2.THRESH_BINARY,
                    )

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

                    cleaned = re.sub(
                        r"[^A-Z ]+",
                        " ",
                        result.upper(),
                    )

                    cleaned = re.sub(
                        r"\s+",
                        " ",
                        cleaned,
                    ).strip()

                    if not cleaned:
                        continue

                    collected_text.append(
                        cleaned
                    )

                    #
                    # Check longer labels before shorter labels.
                    #
                    for label in [
                        "VERY UNLIKELY",
                        "VERY LIKELY",
                        "UNLIKELY",
                        "POSSIBLE",
                        "LIKELY",
                    ]:

                        if label in cleaned:

                            found_text = label
                            found_level = (
                                likelihood_map[
                                    label
                                ]
                            )
                            found_dimension = (
                                "likelihood"
                            )
                            break

                    if found_level is not None:
                        break

                    for label in [
                        "VERY HIGH",
                        "MODERATE",
                        "VERY LOW",
                        "HIGH",
                        "LOW",
                    ]:

                        if label in cleaned:

                            found_text = label
                            found_level = (
                                severity_map[
                                    label
                                ]
                            )
                            found_dimension = (
                                "impact"
                            )
                            break

                    if found_level is not None:
                        break

                if found_level is not None:
                    break

            if found_level is not None:
                break

        if found_level is not None:

            recognized.append(
                {
                    "x":
                        candidate["x"],

                    "value":
                        found_text,

                    "level":
                        found_level,

                    "dimension_guess":
                        found_dimension,

                    "all_ocr":
                        sorted(
                            set(
                                collected_text
                            )
                        ),
                }
            )

    #
    # Sort badge values from left to right.
    #
    recognized.sort(
        key=lambda item:
            item["x"]
    )

    likelihood = None
    impact = None

    evidence = []

    for item in recognized:

        evidence.append(
            (
                f"x={item['x']} | "
                f"text={item['value']} | "
                f"level={item['level']} | "
                f"guess={item['dimension_guess']} | "
                f"ocr={item['all_ocr']}"
            )
        )

    #
    # Prefer explicit likelihood/impact vocabulary first.
    #
    for item in recognized:

        if (
            likelihood is None
            and
            item["dimension_guess"]
            ==
            "likelihood"
        ):

            likelihood = item[
                "level"
            ]

        if (
            impact is None
            and
            item["dimension_guess"]
            ==
            "impact"
        ):

            impact = item[
                "level"
            ]

    #
    # Positional fallback matching the profile layout:
    # left badge = Likelihood
    # right badge = Impact
    #
    if len(recognized) >= 2:

        if likelihood is None:

            likelihood = recognized[
                0
            ][
                "level"
            ]

        if impact is None:

            impact = recognized[
                -1
            ][
                "level"
            ]

    return (
        impact,
        likelihood,
        "\n".join(
            evidence
        ),
    )


'''

text = text[
    :position
] + helper + text[
    position:
]

old = '''        ocr_text = ocr_page(
            pdf_path,
            page_number,
        )

        (
            impact,
            likelihood,
        ) = extract_profile_levels(
            ocr_text,
            label,
        )

        #
        # Fallback to explicit dimension-associated OCR if the
        # positional header could not be read.
        #
        if impact is None:
            impact = level_from_badge(
                ocr_text,
                "impact",
            )

        if likelihood is None:
            likelihood = level_from_badge(
                ocr_text,
                "likelihood",
            )
'''

new = '''        (
            impact,
            likelihood,
            ocr_text,
        ) = extract_colored_profile_badges(
            pdf_path,
            page_number,
        )
'''

if old not in text:
    raise RuntimeError(
        "Could not locate the existing profile extraction block."
    )

text = text.replace(
    old,
    new,
    1,
)

old_unmatched = '''            unmatched.append({
                "Source_Label": label,
                "PDF_Page": page_number,
                "Reason": (
                    "Could not OCR both visual matrix badges. "
                    f"Impact={impact}, Likelihood={likelihood}"
                ),
            })
'''

new_unmatched = '''            unmatched.append({
                "Source_Label": label,
                "PDF_Page": page_number,
                "Reason": (
                    "Could not OCR both visual matrix badges. "
                    f"Impact={impact}, Likelihood={likelihood}"
                ),
                "Evidence": ocr_text[:10000],
            })
'''

if old_unmatched in text:

    text = text.replace(
        old_unmatched,
        new_unmatched,
        1,
    )

compile(
    text,
    str(path),
    "exec",
)

path.write_text(
    text,
    encoding="utf-8",
)

print(
    "SUCCESS: colored badge-region extraction installed."
)
