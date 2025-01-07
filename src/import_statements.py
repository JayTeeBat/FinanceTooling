from __future__ import annotations

import os
import tabula
import pandas as pd

FOLDER = r"E:\My Drive\Vie privee\Famille\Finances\Statements LaBanquePostale"

FILE = r"releve_CCP1126215Y027_20240724.pdf"

FILE_PATH = os.path.join(FOLDER, FILE)


def import_statement(filename: str) -> dict[pd.DataFrame] | pd.DataFrame:
    """

    :param filename: can be a unique filename or a folder name, in which case,
     the function attempts to extract data from all pdf files
    :return: a DataFrame or dict of DataFrame if a folder was passed
    """
    df_temp = tabula.read_pdf(filename)

    return df_temp
