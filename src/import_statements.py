from __future__ import annotations

import decimal
import os
import re
import datetime
import pandas as pd
from tqdm import tqdm
import pdfplumber
from decimal import Decimal


FOLDER = r"E:\My Drive\Vie privee\Famille\Finances\Statements LaBanquePostale"

FILE = r"releve_CCP1126215Y027_20240724.pdf"

FILE_PATH = os.path.join(FOLDER, FILE)

DAY_MONTH_PATTERN = re.compile(r"(0[1-9]|[12][0-9]|3[01])[/\-](0[1-9]|1[012])")
REF_CREDIT_STR_LIST = [
    "VIREMENT DE",
    "CREDIT",
]


def import_all_statements(folder: str) -> dict[str, pd.DataFrame]:
    dfs = {}
    files = [file for file in os.scandir(folder) if file.is_file()]
    for file in tqdm(files):
        dfs[file.name] = import_statement(file.path)

    return dfs


def import_statement(filename: str) -> dict[pd.DataFrame] | pd.DataFrame:
    """

    :param filename: can be a unique filename or a folder name, in which case,
     the function attempts to extract data from all pdf files
    :return: a DataFrame or dict of DataFrame if a folder was passed
    """
    # Extracting raw text from the PDF for analysis
    all_pages_text = []

    # Open the PDF for raw text extraction
    with pdfplumber.open(filename) as pdf:
        # Extract text from each page
        for page_num, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text()
            all_pages_text.append(
                (page_num, page_text)
            )  # Store with page number for reference

    date_pattern = re.compile(
        r"(((?:19|20)\d{2})[/\-]?(0[1-9]|1[012])[/\-]?(0[1-9]|[12][0-9]|3[01]))"
    )
    matches = date_pattern.findall(filename)
    if len(matches) == 0:
        print(f"No date was found in file {filename}")
        # default year to use in datetime format later
        date_year = 1
    else:
        # retrieving the year from the first match
        # assumes the first date found is the actual date of the publication of the doc
        date_year = matches[0][1]
    # Initialize lists to hold extracted transactions
    transactions = []

    # Define a regex pattern to extract transaction rows
    # (Date, Operation, Figure, Detail)
    transaction_pattern = re.compile(
        r"\n(\d{2}/\d{2})\s+"  # capturing date in format DD/MM
        r"([^\n]*?)\s"  # capturing object
        r"(-?(?:\d{1,3}|\d{1,3}(?:(?:\.|\s)\d{3})+),\s?\d{2}?)"
        # capturing amount in format ' XXX XXX,XX\n'
        r"\n(.*)"  # capturing additional description on next line
    )

    # Parse each page's text for transactions
    for page_num, page_text in all_pages_text:
        matches = transaction_pattern.findall(page_text)
        for match in matches:
            # updating date format to include the year
            # reallocation of the last transaction with new format
            transactions.append(sanitize_transaction(date_year, match))

    # Convert extracted transactions into a DataFrame
    columns = ["Date", "Operation", "Amount", "Details"]
    transactions_df = pd.DataFrame(transactions, columns=columns)

    return transactions_df


def sanitize_transaction(
    date_year: str, transaction: re.match
) -> tuple[datetime.date, str, decimal.Decimal, str]:

    day, month = DAY_MONTH_PATTERN.findall(transaction[0])[0]
    # spending by default
    amount = -1 * Decimal(re.sub(r"[^\d\-.]", "", transaction[2].replace(",", ".")))

    if any(
        ref_str.lower() in transaction[1].lower() for ref_str in REF_CREDIT_STR_LIST
    ):
        amount *= -1

    return (
        datetime.date(int(date_year), int(month), int(day)),
        transaction[1],
        amount,
        transaction[3],
    )


if __name__ == "__main__":
    dfs = pd.concat([df for name, df in import_all_statements(FOLDER).items()], axis=0)
    dfs.sort_values("Date", ascending=False, inplace=True)
    dfs.to_excel("Export_LBP_data.xlsx")
