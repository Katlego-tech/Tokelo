"""Read one page inside the `ocr` image, and say what came back (T029).

The tests can't call the reader directly: Tesseract 5 lives in the image this project ships, and
the machine running the tests has either no Tesseract or the wrong one. So they run this, in
there, and read the JSON it prints — which also means the accuracy numbers are measured against
the engine that will actually read a tenant's lease.

    python reader.py <form> <page>     digital | scanned | photo | unreadable
    python reader.py count <form>
"""

import json
import sys
import time

sys.path.insert(0, "/function")

FIXTURES = "/fixtures"


def source_for(form: str, page: int) -> tuple[bytes, str, int]:
    if form == "photo":
        return open(f"{FIXTURES}/photo-{page}.jpg", "rb").read(), "image/jpeg", 1
    if form == "unreadable":
        return open(f"{FIXTURES}/photo-unreadable.jpg", "rb").read(), "image/jpeg", 1
    return open(f"{FIXTURES}/{form}.pdf", "rb").read(), "application/pdf", page


def main(argv: list[str]) -> int:
    from tokelo.ocr import pages

    if argv[0] == "count":
        document, _, _ = source_for(argv[1], 1)
        print(json.dumps({"pages": pages.page_count(document)}))
        return 0

    document, content_type, page = source_for(argv[0], int(argv[1]))
    started = time.monotonic()
    result = pages.read(document, content_type, page)
    print(
        json.dumps(
            {
                "text": result.text,
                "source": result.source,
                "readable": result.readable,
                "seconds": round(time.monotonic() - started, 3),
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
