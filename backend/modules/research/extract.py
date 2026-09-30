"""Deterministic, topic-agnostic claim extraction. No domain names or topics live here — only generic language cues."""
import re, unicodedata
from urllib.parse import urlparse

# ---------- source authority ----------
SOURCE_TYPES = {  # type: (authority weight, label)
    "official": (1.0, "Official / government / regulator"),
    "structured": (0.95, "Structured open data"),
    "reference": (0.85, "Encyclopedia / reference"),
    "news": (0.75, "News / business publication"),
    "research": (0.75, "Market research / analyst report"),
    "company": (0.6, "Company website / press release"),
    "blog": (0.5, "Blog / article"),
    "forum": (0.45, "Discussion / forum"),
    "review": (0.45, "Review platform"),
    "commercial": (0.3, "Commercial / listing site"),
}
FORUM = ("reddit.com", "quora.com", "stackexchange.com", "news.ycombinator.com", "teamblind.com")
REVIEW = ("trustpilot.", "g2.com", "capterra.", "glassdoor.", "ambitionbox.", "mouthshut.", "google.com/maps", "justdial.")
NEWS = ("reuters.", "bloomberg.", "economictimes.", "livemint.", "business-standard.", "moneycontrol.", "thehindu", "hindustantimes.",
        "techcrunch.", "inc42.", "yourstory.", "entrackr.", "the-ken.", "forbes.", "ft.com", "wsj.com", "cnbc.", "bbc.", "nytimes.",
        "theguardian.", "financialexpress.", "indianexpress.", "timesofindia.", "autocarindia.", "businessinsider.")
RESEARCH = ("statista.", "mordorintelligence.", "grandviewresearch.", "marketsandmarkets.", "imarcgroup.", "fortunebusinessinsights.",
            "researchandmarkets.", "mckinsey.", "bcg.com", "bain.com", "deloitte.", "pwc.", "kpmg.", "ey.com", "gartner.", "idc.",
            "tracxn.", "crunchbase.", "cbinsights.", "pitchbook.", "ibef.org")
COMMERCIAL = ("amazon.", "flipkart.", "indiamart.", "olx.", "quikr.", "coupon", "deals")
SKIP_FETCH = ("youtube.com", "youtu.be", "instagram.com", "facebook.com", "pinterest.", "twitter.com", "x.com", "tiktok.com",
              "linkedin.com", "amazon.", "flipkart.", "statista.com")   # statista: paywalled, snippet only


def classify_source(url):
    u = url.lower()
    host = urlparse(u).netloc
    if re.search(r"\.(gov|gouv|gob|nic)\.|\.gov$|europa\.eu|\.gc\.ca|worldbank\.org|imf\.org|oecd\.org|rbi\.org|sebi\.gov", host):
        return "official"
    if "wikipedia.org" in host or "britannica.com" in host or "wikidata.org" in host:
        return "reference"
    for kind, keys in (("review", REVIEW), ("forum", FORUM), ("research", RESEARCH), ("news", NEWS), ("commercial", COMMERCIAL)):
        if any(k in u for k in keys):
            return kind
    return "blog"


# ---------- language cues (generic, any topic) ----------
RISK_CUES = r"\b(?:risk\w*|challeng\w*|concern\w*|problem\w*|issue\w*|shut ?down|shut|clos(?:ed|ure|ing)|losses?|loss-making|fail\w*|declin\w*|" \
            r"struggl\w*|layoffs?|ban(?:ned)?|regulat\w*|penalt\w*|lawsuit|fraud|complaint\w*|barrier\w*|threat\w*|slow(?:down|ing)?|drop(?:ped)?)\b"
OPPORTUNITY_CUES = r"\b(?:opportunit\w*|growth|grow(?:ing|s)?|demand|untapped|gap|underserved|expan\w*|boom\w*|surg\w*|rising|increas\w*|" \
                   r"potential|incentive\w*|subsid\w*|tailwind\w*|adoption)\b"
PRICE_RE = re.compile(r"(?:₹|rs\.?|inr|\$|usd|€|£)\s?\d[\d,.]*(?:\s?(?:k|lakh|crore|cr|mn|million|bn|billion))?|\d[\d,.]*\s?(?:rupees|dollars)", re.I)
FACT_CUES = r"\b(?:founded|launched|established|raised|funding|valuation|revenue|market (?:size|share)|users|customers|subscribers|" \
            r"fleet|employees|cagr|per (?:month|year|day|hour|km)|\d+(?:\.\d+)?\s?%|(?:19|20)\d{2})\b"
OPINION_CUES = r"\b(?:i think|i feel|in my (?:opinion|experience)|imo|we (?:tried|used)|i (?:tried|used|switched)|my experience|personally)\b"
POSITIVE = r"good|great|excellent|best|love\w*|reliable|affordable|cheap|convenient|recommend\w*|impressive|profitable|popular|success\w*"
NEGATIVE = r"bad|poor|worst|terrible|expensive|overpriced|unreliable|broken|scam|rude|disappoint\w*|waste|avoid|delay\w*|unprofitable"
BOILER = r"cookie|subscribe|newsletter|affiliate|sign up|log in|privacy policy|all rights reserved|click here|share this|related posts|follow us|disclaimer|copyright"

# bibliography / reference-list lines: DOIs, URLs, "Surname, X." author lists, "(2022)." years, "14(2), 257-279" volume/pages
CITATION = re.compile(r"doi\.org|\bdoi:|https?://|www\.|\bet al\b|\bpp?\.\s?\d|\bvol\.|\d+\(\d+\)|\(\d{4}[a-z]?\)\.?\s*$|^\W*\(\d{4}\)", re.I)
AUTHORS = re.compile(r"^[A-Z][\w'’-]+,\s(?:[A-Z]\.\s?)+")   # "Fani, V., Mazzoli, V." (case-sensitive)


def is_citation(s):
    """Reference-list entry, not a claim. Also drops lines with too few ordinary words to state anything."""
    return bool(CITATION.search(s) or AUTHORS.search(s)) or len(re.findall(r"\b[a-z]{3,}\b", s)) < 5


RISK, OPP, FACT, OPIN, POS, NEG, BOIL = (re.compile(x, re.I) for x in
                                         (RISK_CUES, OPPORTUNITY_CUES, FACT_CUES, OPINION_CUES, POSITIVE, NEGATIVE, BOILER))


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def split_sentences(text):
    out = []
    for para_i, para in enumerate(re.split(r"\n\s*\n|\n", text)):
        for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'“])", para.strip()):
            s = s.strip(" -•*#\t")
            if 25 <= len(s) <= 450 and not BOIL.search(s) and not s.endswith("?") and not is_citation(s):
                out.append((para_i, s))
    return out


def analyse(sentence, source_type):
    """Classify one sentence. Returns dict or None if it carries no research signal."""
    prices = PRICE_RE.findall(sentence)
    risk, opp, fact, opin = bool(RISK.search(sentence)), bool(OPP.search(sentence)), bool(FACT.search(sentence) or prices), bool(OPIN.search(sentence))
    pos, neg = len(POS.findall(sentence)), len(NEG.findall(sentence))
    if not (risk or opp or fact or opin or pos or neg):
        return None
    kind = "opinion" if opin else "risk" if risk else "opportunity" if opp else "fact" if fact else "opinion"
    if kind == "fact":
        epistemic = "verified" if source_type in ("official", "structured") else "reference" if source_type == "reference" else "reported"
    else:
        epistemic = "reported" if source_type in ("official", "reference", "news", "research") else "opinion"
    return {"kind": kind, "epistemic": epistemic, "sentiment": (pos > neg) - (neg > pos), "prices": prices}


if __name__ == "__main__":
    assert analyse("Bounce raised $150 million in funding in 2021.", "news")["kind"] == "fact"
    assert analyse("Rentals cost ₹1,499 per month for the basic plan.", "company")["prices"] == ["₹1,499"]
    assert analyse("Yulu faces regulatory challenges in several cities.", "news")["kind"] == "risk"
    assert analyse("I think the scooters are unreliable and overpriced.", "forum")["epistemic"] == "opinion"
    assert analyse("The weather was pleasant.", "blog") is None
    for ref in ["Fani, V., Mazzoli, V., & Acuti, D. (2022).", "Sustainability, 14(4), 1945. https://doi.org/10.3390/su14041945",
                "Factors affecting sustainable fashion consumption: A systematic review and research orientations. (2024).",
                "Gwozdz, W., Nielsen, K.S. and Müller, T. (2017) 'An environmental perspective on clothing consumption', Sustainability, 9(5), p."]:
        assert is_citation(ref), ref
    assert not is_citation("Yulu raised $82 million in 2021 and operates about 18,000 scooters in Bengaluru.")
    assert not is_citation("Bounce faces rising costs and several customers report poor battery life.")
    assert classify_source("https://www.reddit.com/r/bangalore/comments/x") == "forum"
    assert classify_source("https://morth.nic.in/x") == "official"
    assert classify_source("https://inc42.com/buzz/x") == "news"
    print("extract self-check ok")
