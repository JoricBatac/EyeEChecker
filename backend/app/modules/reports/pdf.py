"""PDF rendering. Photos are embedded only in PDFs generated before photo deletion (sign-off)."""

from __future__ import annotations

import io

from fpdf import FPDF


def _latin1(text: str) -> str:
    # Core PDF fonts are Latin-1; Filipino text fits, anything else degrades gracefully.
    return (
        text.replace("’", "'")
        .replace("–", "-")
        .replace("—", "-")
        .encode("latin-1", "replace")
        .decode("latin-1")
    )


class _Doc(FPDF):
    def __init__(self, clinic_name: str, clinic_address: str | None, footer_text: str):
        super().__init__(format="A4")
        self.clinic_name = clinic_name
        self.clinic_address = clinic_address
        self.footer_text = footer_text
        self.set_auto_page_break(auto=True, margin=18)

    def header(self) -> None:
        self.set_font("Helvetica", "B", 12)
        self.cell(0, 6, _latin1(self.clinic_name), new_x="LMARGIN", new_y="NEXT")
        if self.clinic_address:
            self.set_font("Helvetica", "", 9)
            self.cell(0, 5, _latin1(self.clinic_address), new_x="LMARGIN", new_y="NEXT")
        self.line(self.l_margin, self.get_y() + 1, self.w - self.r_margin, self.get_y() + 1)
        self.ln(4)

    def footer(self) -> None:
        self.set_y(-14)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 5, _latin1(self.footer_text), align="L")
        self.cell(0, 5, f"Page {self.page_no()}", align="R")


def render_pdf(
    content: str,
    *,
    clinic_name: str,
    clinic_address: str | None,
    footer_text: str,
    photos: list[tuple[str, bytes]] | None = None,
) -> bytes:
    pdf = _Doc(clinic_name, clinic_address, footer_text)
    pdf.add_page()
    width = pdf.w - pdf.l_margin - pdf.r_margin

    for raw in content.splitlines():
        line = _latin1(raw.rstrip())
        if not line:
            pdf.ln(2)
        elif line.startswith("# "):
            pdf.set_font("Helvetica", "B", 15)
            pdf.multi_cell(width, 8, line[2:], new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)
        elif line.startswith("## "):
            pdf.ln(1)
            pdf.set_font("Helvetica", "B", 11)
            pdf.multi_cell(width, 6, line[3:], new_x="LMARGIN", new_y="NEXT")
        elif line.startswith("- "):
            pdf.set_font("Helvetica", "", 10)
            pdf.set_x(pdf.l_margin + 4)
            pdf.multi_cell(width - 4, 5, "- " + line[2:], markdown=True, new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.set_font("Helvetica", "", 10)
            pdf.multi_cell(width, 5, line, markdown=True, new_x="LMARGIN", new_y="NEXT")

    if photos:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 6, "Photos", new_x="LMARGIN", new_y="NEXT")
        col_w = (width - 6) / 2
        box_h = col_w * 0.75
        row_y = pdf.get_y()
        for i, (label, data) in enumerate(photos):
            col = i % 2
            if col == 0:
                row_y = pdf.get_y()
                if row_y + box_h + 10 > pdf.h - 20:
                    pdf.add_page()
                    row_y = pdf.get_y()
            x = pdf.l_margin + col * (col_w + 6)
            pdf.image(io.BytesIO(data), x=x, y=row_y, w=col_w, h=box_h, keep_aspect_ratio=True)
            pdf.set_xy(x, row_y + box_h + 1)
            pdf.set_font("Helvetica", "", 8)
            pdf.cell(col_w, 4, _latin1(label))
            if col == 1 or i == len(photos) - 1:
                pdf.set_y(row_y + box_h + 8)

    return bytes(pdf.output())
