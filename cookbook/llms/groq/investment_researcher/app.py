import time
import random
import feedparser
import urllib.parse
import nest_asyncio
import yfinance as yf
import streamlit as st
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
from duckduckgo_search.exceptions import RatelimitException
from phi.assistant import Assistant
from phi.utils.log import logger
import re  # Import regular expressions module for keyword tokenization

from assistants import get_invstment_research_assistant  # type: ignore

nest_asyncio.apply()
st.set_page_config(
    page_title="Investment Researcher",
    page_icon=":orange_heart:",
)
st.title("Investment Researcher")
st.markdown("##### :orange_heart: Built using [phidata](https://github.com/phidatahq/phidata)")

def clean_html(raw_html):
    soup = BeautifulSoup(raw_html, 'html.parser')
    return soup.get_text()

def fetch_news_from_google_news(keywords):
    print(f"Fetching Google News RSS feed for query: {keywords}")
    query = urllib.parse.quote(keywords)
    feed_url = f'https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en'
    feed = feedparser.parse(feed_url)
    print(f"Found {len(feed.entries)} entries in Google News feed.")
    company_news = []
    for entry in feed.entries:
        summary = entry.get('summary', '')
        title = entry.get('title', '')
        news_item = {
            'title': title,
            'link': entry.get('link', ''),
            'published': entry.get('published', ''),
            'summary': summary,
        }
        company_news.append(news_item)
    print(f"Total news articles from Google News: {len(company_news)}")
    return company_news

def fetch_news_from_rss(keywords):
    rss_feeds = [
        'https://feeds.a.dj.com/rss/RSSMarketsMain.xml',  # Wall Street Journal - Markets
        'https://www.cnbc.com/id/100003114/device/rss/rss.html',  # CNBC - Market News
        'https://www.marketwatch.com/rss/topstories',  # MarketWatch - Top Stories
        'https://finance.yahoo.com/news/rssindex',  # Yahoo Finance - News
    ]

    company_news = []
    keyword_tokens = re.findall(r'\w+', keywords.lower())
    print(f"Keyword tokens for filtering: {keyword_tokens}")
    for feed_url in rss_feeds:
        print(f"Fetching RSS feed from: {feed_url}")
        feed = feedparser.parse(feed_url)
        print(f"Found {len(feed.entries)} entries in the feed.")
        for entry in feed.entries:
            summary = entry.get('summary', '').lower()
            title = entry.get('title', '').lower()
            content = title + ' ' + summary
            if any(token in content for token in keyword_tokens):
                news_item = {
                    'title': entry.get('title', ''),
                    'link': entry.get('link', ''),
                    'published': entry.get('published', ''),
                    'summary': entry.get('summary', ''),
                }
                company_news.append(news_item)
    print(f"Total news articles from RSS: {len(company_news)}")
    return company_news

def fetch_ddg_news_with_retries(keywords, retries=3):
    ddgs = DDGS()  # Initialize the DDGS instance
    print(f"Fetching DuckDuckGo news for query: {keywords}")
    for i in range(retries):
        try:
            # Attempt to fetch the news
            company_news = ddgs.news(keywords=keywords, max_results=5)
            print(f"Found {len(company_news)} articles from DuckDuckGo.")
            return company_news
        except RatelimitException:
            # Handle rate limit exception by waiting before retrying
            wait_time = (2 ** i) + random.uniform(0, 1)  # Exponential backoff with jitter
            print(f"Rate limit hit, retrying in {wait_time:.2f} seconds...")
            time.sleep(wait_time)
    print("Failed to fetch news from DuckDuckGo after retries.")
    return []

def fetch_news(keywords):
    company_news = []
    # Fetch news from RSS feeds
    rss_news = fetch_news_from_rss(keywords)
    company_news.extend(rss_news)
    # Fetch news from Google News RSS
    google_news = fetch_news_from_google_news(keywords)
    company_news.extend(google_news)
    # Fetch news from DuckDuckGo with retries
    ddg_news = []
    try:
        ddg_news = fetch_ddg_news_with_retries(keywords)
        # Process DDG news items to match the data structure
        for item in ddg_news:
            news_item = {
                'title': item.get('title', ''),
                'link': item.get('url', ''),
                'published': item.get('date', ''),
                'summary': item.get('body', ''),
            }
            company_news.append(news_item)
    except Exception as e:
        print(f"Error fetching news from DuckDuckGo: {e}")
    total_news = len(company_news)
    print(f"Total news articles before deduplication: {total_news}")
    # Remove duplicates based on the news title
    unique_news = {item['title']: item for item in company_news if item['title']}
    print(f"Total unique news articles after deduplication: {len(unique_news)}")
    return list(unique_news.values())

def restart_assistant():
    logger.debug("---*--- Restarting Assistant ---*---")
    st.session_state["research_assistant"] = None
    st.rerun()

def main() -> None:
    # Get LLM Model
    model = (
        st.sidebar.selectbox("Select LLM", options=["llama3-70b-8192", "llama3-8b-8192", "mixtral-8x7b-32768", "llama-3.2-3b-preview", "llama-3.1-8b-instant"])
        or "llama3-70b-8192"
    )
    # Set llm in session state
    if "model" not in st.session_state:
        st.session_state["model"] = model
    # Restart the assistant if model changes
    elif st.session_state["model"] != model:
        st.session_state["model"] = model
        restart_assistant()

    # Get the assistant
    research_assistant: Assistant
    if "research_assistant" not in st.session_state or st.session_state["research_assistant"] is None:
        research_assistant = get_invstment_research_assistant(model=model)
        st.session_state["research_assistant"] = research_assistant
    else:
        research_assistant = st.session_state["research_assistant"]

    # Get ticker for report
    ticker_to_research = st.sidebar.text_input(
        ":female-scientist: Enter a ticker to research",
        value="NVDA",
    )

    # Checkboxes for research options
    st.sidebar.markdown("## Research Options")
    get_company_info = st.sidebar.checkbox("Company Info", value=True)
    get_company_news = st.sidebar.checkbox("Company News", value=True)
    get_analyst_recommendations = st.sidebar.checkbox("Analyst Recommendations", value=True)
    get_upgrades_downgrades = st.sidebar.checkbox("Upgrades/Downgrades", value=True)

    # Ticker object
    ticker = yf.Ticker(ticker_to_research)

    # -*- Generate Research Report
    generate_report = st.sidebar.button("Generate Report")
    if generate_report:
        report_input = ""

        # Get company information and search keywords
        company_info_full = ticker.info
        company_name_full = company_info_full.get("shortName", ticker_to_research)
        # Remove suffixes
        company_name = company_name_full.split(',')[0]
        search_keywords = f"{company_name} {ticker_to_research}"
        print(f"Company name for search: {company_name}")
        print(f"Search keywords: {search_keywords}")

        if get_company_info:
            with st.status("Getting Company Info", expanded=True) as status:
                with st.container():
                    company_info_container = st.empty()
                    if company_info_full:
                        company_info_container.json(company_info_full)
                        #Excluding less critical info to save tokens
                        company_info_cleaned = {
                            "Name": company_info_full.get("shortName"),
                            "Symbol": company_info_full.get("symbol"),
                            "Current Stock Price": f"{company_info_full.get('regularMarketPrice', company_info_full.get('currentPrice'))} {company_info_full.get('currency', 'USD')}",
                            "Market Cap": f"{company_info_full.get('marketCap', company_info_full.get('enterpriseValue'))} {company_info_full.get('currency', 'USD')}",
                            "Sector": company_info_full.get("sector"),
                            "Industry": company_info_full.get("industry"),
                            # "Address": company_info_full.get("address1"),
                            "City": company_info_full.get("city"),
                            # "State": company_info_full.get("state"),
                            # "Zip": company_info_full.get("zip"),
                            # "Country": company_info_full.get("country"),
                            "EPS": company_info_full.get("trailingEps"),
                            "P/E Ratio": company_info_full.get("trailingPE"),
                            "52 Week Low": company_info_full.get("fiftyTwoWeekLow"),
                            "52 Week High": company_info_full.get("fiftyTwoWeekHigh"),
                            "50 Day Average": company_info_full.get("fiftyDayAverage"),
                            "200 Day Average": company_info_full.get("twoHundredDayAverage"),
                            "Website": company_info_full.get("website"),
                            "Summary": company_info_full.get("longBusinessSummary"),
                            "Analyst Recommendation": company_info_full.get("recommendationKey"),
                            "Number Of Analyst Opinions": company_info_full.get("numberOfAnalystOpinions"),
                            "Employees": company_info_full.get("fullTimeEmployees"),
                            "Total Cash": company_info_full.get("totalCash"),
                            "Free Cash flow": company_info_full.get("freeCashflow"),
                            "Operating Cash flow": company_info_full.get("operatingCashflow"),
                            "EBITDA": company_info_full.get("ebitda"),
                            "Revenue Growth": company_info_full.get("revenueGrowth"),
                            "Gross Margins": company_info_full.get("grossMargins"),
                            "Ebitda Margins": company_info_full.get("ebitdaMargins"),
                        }
                        company_info_md = "## Company Info\n\n"
                        for key, value in company_info_cleaned.items():
                            if value:
                                company_info_md += f"  - {key}: {value}\n\n"
                        report_input += "Company Info: \n\n"
                        report_input += company_info_md
                        report_input += "---\n"
                    else:
                        company_info_container.info("No company information found.")
                status.update(label="Company Info available", state="complete", expanded=False)

        if get_company_news:
            with st.status("Getting Company News", expanded=True) as status:
                with st.container():
                    company_news_container = st.empty()
                    company_news = []

                    try:
                        company_news = fetch_news(search_keywords)
                        company_news_container.json(company_news)
                    except Exception as e:
                        print(f"Error: {e}")
                        company_news_container.error("Failed to fetch company news.")

                    if len(company_news) > 0:
                        company_news_md = "## Company News\n\n"
                        for news_item in company_news:
                            title = news_item.get('title', '')
                            if title:
                                company_news_md += f"### {title}\n\n"
                            published = news_item.get('published', '')
                            if published:
                                company_news_md += f"- **Date**: {published}\n"
                            link = news_item.get('link', '')
                            # Commenting out link to save on tokens:
                            # if link:
                            #     company_news_md += f"- **Link**: [{link}]({link})\n"
                            summary = news_item.get('summary', '')
                            if summary:
                                summary = clean_html(summary)
                                company_news_md += f"\n{summary}\n"
                            company_news_md += "\n---\n"
                        company_news_container.markdown(company_news_md)
                        # Add news to report input
                        report_input += "This section contains the most recent news articles about the company.\n\n"
                        report_input += company_news_md
                        report_input += "---\n"
                    else:
                        company_news_container.info("No recent news found for this company.")
                status.update(label="Company News available", state="complete", expanded=False)

        if get_analyst_recommendations:
            with st.status("Getting Analyst Recommendations", expanded=True) as status:
                with st.container():
                    analyst_recommendations_container = st.empty()
                    analyst_recommendations = ticker.recommendations
                    if analyst_recommendations is not None and not analyst_recommendations.empty:
                        analyst_recommendations_container.write(analyst_recommendations)
                        analyst_recommendations_md = analyst_recommendations.to_markdown()
                        report_input += "## Analyst Recommendations\n\n"
                        report_input += "This table outlines the most recent analyst recommendations for the stock.\n\n"
                        report_input += f"{analyst_recommendations_md}\n"
                        report_input += "---\n"
                    else:
                        analyst_recommendations_container.info("No analyst recommendations found.")
                status.update(label="Analyst Recommendations available", state="complete", expanded=False)

        if get_upgrades_downgrades:
            with st.status("Getting Upgrades/Downgrades", expanded=True) as status:
                with st.container():
                    upgrades_downgrades_container = st.empty()
                    upgrades_downgrades = ticker.upgrades_downgrades
                    if upgrades_downgrades is not None and not upgrades_downgrades.empty:
                        upgrades_downgrades = upgrades_downgrades.head(20)
                        upgrades_downgrades_container.write(upgrades_downgrades)
                        upgrades_downgrades_md = upgrades_downgrades.to_markdown()
                        report_input += "## Upgrades/Downgrades\n\n"
                        report_input += "This table outlines the most recent upgrades and downgrades for the stock.\n\n"
                        report_input += f"{upgrades_downgrades_md}\n"
                        report_input += "---\n"
                    else:
                        upgrades_downgrades_container.info("No upgrades/downgrades found.")
                status.update(label="Upgrades/Downgrades available", state="complete", expanded=False)

        with st.status("Generating Draft", expanded=True) as status:
            with st.container():
                draft_report_container = st.empty()
                draft_report_container.markdown(report_input)
            status.update(label="Draft Generated", state="complete", expanded=False)

        with st.spinner("Generating Report"):
            final_report = ""
            final_report_container = st.empty()
            report_message = f"Please generate a report about: {company_name_full}\n\n"
            report_message += "Include analysis of the latest news articles provided below.\n\n"
            report_message += report_input
            print("Report message prepared for assistant:")
            print(report_message)
            for delta in research_assistant.run(report_message):
                final_report += delta  # type: ignore
                final_report_container.markdown(final_report)

    st.sidebar.markdown("---")
    if st.sidebar.button("New Run"):
        restart_assistant()

main()
