from __future__ import annotations

import os
import tabula
import pandas as pd
import pdfplumber

FOLDER = r"E:\My Drive\Vie privee\Famille\Finances\Statements LaBanquePostale"

FILE = r"releve_CCP1126215Y027_20240724.pdf"

FILE_PATH = os.path.join(FOLDER, FILE)


def import_statement(filename: str) -> dict[pd.DataFrame] | pd.DataFrame:
    """

    :param filename: can be a unique filename or a folder name, in which case,
     the function attempts to extract data from all pdf files
    :return: a DataFrame or dict of DataFrame if a folder was passed
    """
    import re

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

    # Initialize lists to hold extracted transactions
    transactions = []

    # Define a regex pattern to extract transaction rows
    # (Date, Operation, Figure, Detail)
    transaction_pattern = re.compile(
        r"(^\d{2}\/\d{2})\s+"
        r"([^\n]*?)\s+"
        r"(-?(?:\d{1,3}|\d{1,3}(?:(?:\.|\s)\d{3})+)(?:,\s?\d*)?)$\s+"
        r"(.+\n)"
    )

    # Parse each page's text for transactions
    for page_num, page_text in all_pages_text:
        matches = transaction_pattern.findall(page_text)
        for match in matches:
            transactions.append(match)

    # Convert extracted transactions into a DataFrame
    columns = ["Date", "Operation", "Debit (€)", "Credit (€)"]
    transactions_df = pd.DataFrame(transactions, columns=columns)

    return transactions_df
