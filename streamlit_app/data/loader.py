"""File-upload handling and cached raw-sheet loading."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st


@st.cache_data(ttl=300, show_spinner="Loading workbook…")
def load_all_sheets(file: Any) -> dict[str, pd.DataFrame]:
    """Load every sheet from the uploaded Excel workbook as raw DataFrames."""
    return pd.read_excel(file, sheet_name=None, header=None)
