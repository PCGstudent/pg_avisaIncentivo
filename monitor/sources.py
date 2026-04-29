"""Sources to monitor for new EV incentive announcements (Portugal)."""

from dataclasses import dataclass, field


@dataclass
class Source:
    name: str
    url: str
    kind: str  # "html" or "rss"
    # CSS selector to narrow the HTML region we hash. None = whole page text.
    selector: str | None = None
    # Keywords that, if newly present, escalate severity to ALERT.
    alert_keywords: list[str] = field(default_factory=list)


ALERT_KEYWORDS_DEFAULT = [
    "2026",
    "Mobilidade Verde",
    "candidaturas",
    "abertas",
    "aviso",
    "formulário",
    "formulario",
    "veículos elétricos",
    "veiculos eletricos",
]


SOURCES: list[Source] = [
    # --- Fundo Ambiental (primary) ---
    Source(
        name="FundoAmbiental_Apoios",
        url="https://www.fundoambiental.pt/apoios-2025.aspx",
        kind="html",
        selector="main",
        alert_keywords=ALERT_KEYWORDS_DEFAULT,
    ),
    Source(
        name="FundoAmbiental_MobilidadeVerde2025_2026",
        url="https://www.fundoambiental.pt/apoios-2025/mitigacao-as-alteracoes-climaticas/introducao-no-consumo-de-veiculos-de-emissoes-nulas-no-ano-de-2025-mobilidade-verde-passageiros2.aspx",
        kind="html",
        selector="main",
        alert_keywords=ALERT_KEYWORDS_DEFAULT,
    ),
    Source(
        name="FundoAmbiental_Home",
        url="https://www.fundoambiental.pt/",
        kind="html",
        selector="main",
        alert_keywords=ALERT_KEYWORDS_DEFAULT,
    ),
    # --- Government portal ---
    Source(
        name="Gov_Ambiente_Comunicados",
        url="https://www.portugal.gov.pt/pt/gc24/comunicacao/comunicados?i=ambiente-energia",
        kind="html",
        selector="main",
        alert_keywords=ALERT_KEYWORDS_DEFAULT,
    ),
    # --- News (RSS) ---
    Source(
        name="GoogleNews_FundoAmbiental_VE",
        url="https://news.google.com/rss/search?q=%22Fundo+Ambiental%22+%22carros+el%C3%A9tricos%22&hl=pt-PT&gl=PT&ceid=PT:pt-150",
        kind="rss",
        alert_keywords=ALERT_KEYWORDS_DEFAULT,
    ),
    Source(
        name="GoogleNews_MobilidadeVerde",
        url="https://news.google.com/rss/search?q=%22Mobilidade+Verde%22+incentivo+2026&hl=pt-PT&gl=PT&ceid=PT:pt-150",
        kind="rss",
        alert_keywords=ALERT_KEYWORDS_DEFAULT,
    ),
    Source(
        name="GoogleNews_IncentivoEletrico",
        url="https://news.google.com/rss/search?q=incentivo+%22carro+el%C3%A9trico%22+Portugal+2026&hl=pt-PT&gl=PT&ceid=PT:pt-150",
        kind="rss",
        alert_keywords=ALERT_KEYWORDS_DEFAULT,
    ),
]
