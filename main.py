import datetime
import os.path
import pickle
import time

from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from prometheus_client import start_http_server, Gauge

# If modifying these scopes, delete the file token.pickle.
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

FINANCE_SPREADSHEET_ID = os.getenv("FINANCE_SPREADSHEET_ID")
SKIP_WRITING_CREDS = os.getenv("RO_FILESYSTEM") != ""
PORT = int(os.getenv("PORT", 8080))
IGNORED_SHEETS = ["Template", "Categories", "IRA/401k/HSA log"]
CREDS_PATH = os.getenv("CRED_PATH", "/opt/app/.creds/token.pickle")


def get_google_creds():
    creds = None
    # The file token.pickle stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists(CREDS_PATH):
        with open(CREDS_PATH, "rb") as token:
            creds = pickle.load(token)

    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_console()
        # Save the credentials for the next run
        # cloud functions have a read-only fs so just refresh the token every time
        if not SKIP_WRITING_CREDS:
            with open(CREDS_PATH, "wb") as token:
                pickle.dump(creds, token)

    return creds


def deserialize_sheets(accounts, value_ranges, days=30):
    all_transactions = []
    for idx in range(len(accounts)):
        values = value_ranges[idx]["values"]
        headings = values[0]
        name_idx = headings.index("Name")
        date_idx = headings.index("Date")
        amount_idx = headings.index("Effective Amount")
        category_idx = headings.index("Effective Category")
        ack_idx = headings.index("Ack")

        # ignore the first row, it's just labels
        values = values[1:]

        # only use ack'd transactions
        values = list(filter(lambda v: v[ack_idx] == "Yes", values))

        transactions = [
            {
                "account": accounts[idx],
                "name": value[name_idx],
                "date": datetime.datetime.strptime(value[date_idx], "%Y-%m-%d"),
                "amount": value[amount_idx],
                "category": value[category_idx],
            }
            for value in values
        ]

        # filter out dates before days ago
        transactions = list(
            filter(
                lambda t: t["date"]
                > datetime.datetime.now() - datetime.timedelta(days=days),
                transactions,
            )
        )

        all_transactions += transactions
    return all_transactions


def get_labels(transaction):
    return {
        "account": transaction["account"],
        "name": transaction["name"],
        "category": transaction["category"],
        "date": transaction["date"].timestamp(),
    }


def get_metrics(service):
    spreadsheet = (
        service.spreadsheets().get(spreadsheetId=FINANCE_SPREADSHEET_ID).execute()
    )
    titles = [sheet["properties"]["title"] for sheet in spreadsheet["sheets"]]
    titles = list(filter(lambda t: t not in IGNORED_SHEETS, titles))

    resp = (
        service.spreadsheets()
        .values()
        .batchGet(spreadsheetId=FINANCE_SPREADSHEET_ID, ranges=titles)
        .execute()
    )
    all_transactions = deserialize_sheets(titles, resp["valueRanges"], days=30)

    timestamps = Gauge(
        "transaction_timestamp_epoch_seconds",
        "When transactions occured",
        ["account", "name", "category", "date"],
    )
    amounts = Gauge(
        "transaction_amount_cents",
        "The transaction value",
        ["account", "name", "category", "date"],
    )
    for t in all_transactions:
        labels = get_labels(t)
        timestamps.labels(**labels).set(t["date"].timestamp())
        amounts.labels(**labels).set(round(float(t["amount"]) * 100))


if __name__ == "__main__":
    start_http_server(PORT)

    creds = get_google_creds()
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)

    while True:
        get_metrics(service)
        time.sleep(60 * 60 * 24)
