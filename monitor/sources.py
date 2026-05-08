"""Sources to monitor for new EV incentive announcements (Portugal)."""

from dataclasses import dataclass, field


@dataclass
class Source:
    name: str
    url: str
    kind: str  # "html" or "rss"
    # OFFICIAL = government-owned page (high trust). NEWS = press / aggregator.
    tier: str = "NEWS"
    # CSS selector to narrow the HTML region we hash. None = whole page text.
    selector: str | None = None


# Keywords used to score how strong a signal is.
# Score >= 2 OR a "definitive" phrase => CRITICAL.
# Otherwise we just track the change as informational.
DEFINITIVE_PHRASES = [
    "candidaturas abertas",
    "candidaturas abriram",
    "candidaturas estão abertas",
    "candidaturas estao abertas",
    "aviso publicado",
    "aviso aberto",
    "aviso n.º",
    "aviso nº",
    "aviso n.o",
    "abertura de candidaturas",
    "abertura do aviso",
    "abriu o aviso",
    "abriram as candidaturas",
    "novo aviso",
    "formulário de candidatura",
    "formulario de candidatura",
    "submeter candidatura",
    "submissão de candidaturas",
    "submissao de candidaturas",
    "início das candidaturas",
    "inicio das candidaturas",
    "regulamento publicado",
    "incentivo aberto",
    "candidaturas a partir de",
]

STRONG_KEYWORDS = [
    "candidaturas",
    "candidatura",
    "aviso",
    "formulário",
    "formulario",
    "submissão",
    "submissao",
    "dotação",
    "dotacao",
]

CONTEXT_KEYWORDS = [
    "mobilidade verde",
    "fundo ambiental",
    "veículos elétricos",
    "veiculos eletricos",
    "carros elétricos",
    "carros eletricos",
    "incentivo",
    "subsídio",
    "subsidio",
    "2026",
]


SOURCES: list[Source] = [
    # --- Fundo Ambiental: páginas conhecidas ---
    Source(
        name="FundoAmbiental_Home",
        url="https://www.fundoambiental.pt/",
        kind="html",
        tier="OFFICIAL",
        selector="main",
    ),
    Source(
        name="FundoAmbiental_Apoios2025",
        url="https://www.fundoambiental.pt/apoios-2025.aspx",
        kind="html",
        tier="OFFICIAL",
        selector="main",
    ),
    Source(
        name="FundoAmbiental_MobilidadeVerde2025_2026",
        url="https://www.fundoambiental.pt/apoios-2025/mitigacao-as-alteracoes-climaticas/introducao-no-consumo-de-veiculos-de-emissoes-nulas-no-ano-de-2025-mobilidade-verde-passageiros2.aspx",
        kind="html",
        tier="OFFICIAL",
        selector="main",
    ),
    # --- Fundo Ambiental: URLs preventivas para 2026 ---
    Source(
        name="FundoAmbiental_Apoios2026_Guess",
        url="https://www.fundoambiental.pt/apoios-2026.aspx",
        kind="html",
        tier="OFFICIAL",
        selector="main",
    ),
    Source(
        name="FundoAmbiental_MobilidadeVerde2026_Guess",
        url="https://www.fundoambiental.pt/apoios-2026/mitigacao-as-alteracoes-climaticas/introducao-no-consumo-de-veiculos-de-emissoes-nulas-no-ano-de-2026-mobilidade-verde-passageiros.aspx",
        kind="html",
        tier="OFFICIAL",
        selector="main",
    ),
    Source(
        name="FundoAmbiental_AvisosAbertos",
        url="https://www.fundoambiental.pt/avisos-abertos.aspx",
        kind="html",
        tier="OFFICIAL",
        selector="main",
    ),
    # --- Portal do Governo ---
    Source(
        name="Gov_Ambiente_Comunicados",
        url="https://www.portugal.gov.pt/pt/gc24/comunicacao/comunicados?i=ambiente-energia",
        kind="html",
        tier="OFFICIAL",
        selector="main",
    ),
    Source(
        name="Gov_Ambiente_Noticias",
        url="https://www.portugal.gov.pt/pt/gc24/comunicacao/noticias?i=ambiente-energia",
        kind="html",
        tier="OFFICIAL",
        selector="main",
    ),
    # --- e-Portugal: portal único de serviços públicos.
    # Mesmo a página de "0 resultados" muda quando aparecer 1 resultado novo,
    # disparando ALERT.
    Source(
        name="ePortugal_IncentivoEV",
        url="https://eportugal.gov.pt/pesquisa?search=incentivo+veiculos+eletricos",
        kind="html",
        tier="OFFICIAL",
        selector="main",
    ),
    # --- Google News com query apertada: "Mobilidade Verde" + 2026.
    # A query original (genérica) trazia avisos DRE não relacionados que
    # apenas mencionavam Fundo Ambiental — disparou um falso CRITICAL no
    # primeiro run (Aviso n.º 5656/2024/2 não-EV). Com "Mobilidade Verde"
    # forçado entre aspas a fonte fica focada no programa que nos importa.
    Source(
        name="GoogleNews_DRE_MobilidadeVerde",
        url="https://news.google.com/rss/search?q=%22Mobilidade+Verde%22+(aviso+OR+%22Di%C3%A1rio+da+Rep%C3%BAblica%22)+2026&hl=pt-PT&gl=PT&ceid=PT:pt-150",
        kind="rss",
        tier="NEWS",
    ),
    # --- ACAP ---
    Source(
        name="ACAP_Noticias",
        url="https://acap.pt/category/noticias/",
        kind="html",
        tier="NEWS",
        selector="main",
    ),
    # --- News RSS (Google News PT) ---
    Source(
        name="GoogleNews_FundoAmbiental_VE",
        url="https://news.google.com/rss/search?q=%22Fundo+Ambiental%22+%22carros+el%C3%A9tricos%22&hl=pt-PT&gl=PT&ceid=PT:pt-150",
        kind="rss",
        tier="NEWS",
    ),
    Source(
        name="GoogleNews_MobilidadeVerde",
        url="https://news.google.com/rss/search?q=%22Mobilidade+Verde%22+incentivo+2026&hl=pt-PT&gl=PT&ceid=PT:pt-150",
        kind="rss",
        tier="NEWS",
    ),
    Source(
        name="GoogleNews_IncentivoEletrico",
        url="https://news.google.com/rss/search?q=incentivo+%22carro+el%C3%A9trico%22+Portugal+2026&hl=pt-PT&gl=PT&ceid=PT:pt-150",
        kind="rss",
        tier="NEWS",
    ),
    Source(
        name="GoogleNews_AvisoFundoAmbiental",
        url="https://news.google.com/rss/search?q=%22Fundo+Ambiental%22+aviso+candidaturas&hl=pt-PT&gl=PT&ceid=PT:pt-150",
        kind="rss",
        tier="NEWS",
    ),
    Source(
        name="GoogleNews_PAEPlus",
        url="https://news.google.com/rss/search?q=%22PAE%2B%22+OR+%22Programa+de+Apoio%22+el%C3%A9trico&hl=pt-PT&gl=PT&ceid=PT:pt-150",
        kind="rss",
        tier="NEWS",
    ),
    Source(
        name="GoogleNews_Subsidio2026",
        url="https://news.google.com/rss/search?q=subs%C3%ADdio+%22carro+el%C3%A9trico%22+2026+Portugal&hl=pt-PT&gl=PT&ceid=PT:pt-150",
        kind="rss",
        tier="NEWS",
    ),
]
