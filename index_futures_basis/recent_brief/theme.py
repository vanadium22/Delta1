"""Muted colors for the opening contract tables; chart colors stay unchanged."""

INK, RED = "#354152", "#987A80"
HEADER, BORDER = "505D6B", "D9DDE3"
PRODUCT_COLORS = (
    ("5D6E82", ("E8EDF2", "EFF2F6", "F5F7FA", "FBFCFD")),
    ("68717D", ("E9ECEF", "F0F2F4", "F6F7F9", "FCFDFE")),
    ("857A6D", ("F0ECE6", "F5F2ED", "F9F7F3", "FDFCF9")),
    ("7D728A", ("EDE9F1", "F3EFF6", "F8F5FA", "FDFBFE")),
)


def setup():
    from .charts import setup as base_setup
    import matplotlib.pyplot as plt

    base_setup()
    plt.rcParams.update(
        {
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )
