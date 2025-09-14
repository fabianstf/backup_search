import json
from typing import Any, Dict, List

import streamlit as st

from backup_exec_api import search_catalog, DEFAULT_BEMCLI_MODULE_PATH


st.set_page_config(page_title="Backup Exec Catalog Search", layout="wide")

st.title("Backup Exec Catalog Search")
st.caption("Search the Backup Exec catalog by path using BEMCLI")

with st.form("search_form"):
    path = st.text_input("Path (use wildcards like *)", value=r"C:\\Data\\Projects\\*")
    col1, col2, col3 = st.columns(3)
    with col1:
        agent = st.text_input("Agent (optional)", value="")
    with col2:
        modulepath = st.text_input("BEMCLI module path (optional)", value=DEFAULT_BEMCLI_MODULE_PATH)
    with col3:
        show_debug = st.checkbox("Show debug info", value=True)
    col4, col5 = st.columns(2)
    with col4:
        recurse = st.checkbox("Recurse subfolders (-Recurse)", value=False)
    with col5:
        is_dir = st.checkbox("Path is directory (-PathIsDirectory)", value=False)
    submitted = st.form_submit_button("Search")

if submitted:
    if not path.strip():
        st.error("Please enter a path.")
    else:
        with st.spinner("Searching…"):
            result: Dict[str, Any] = search_catalog(
                path=path.strip(),
                agent_server=agent.strip() or None,
                module_path=modulepath.strip() or None,
                recurse=recurse,
                path_is_directory=is_dir,
            )

        if not result.get("success"):
            st.error(result.get("error") or "Search failed.")
        else:
            items: List[Dict[str, Any]] = result.get("results", [])
            st.success(f"Found {len(items)} item(s)")

            if len(items) == 0:
                st.info("No results found.")
            else:
                cols = [
                    ("Resource", "ResourceName"),
                    ("Name", "Name"),
                    ("Type", "ItemType"),
                    ("Size", "SizeBytes"),
                    ("Modified", "ModifiedTime"),
                ]

                def has_any_key(item: Dict[str, Any], key: str) -> bool:
                    return key in item and item[key] is not None

                preview = items[:5]
                if any(any(has_any_key(it, k) for _, k in cols) for it in preview):
                    table_rows: List[Dict[str, Any]] = []
                    for it in items:
                        row = {}
                        for label, key in cols:
                            row[label] = it.get(key, "")
                        table_rows.append(row)
                    st.dataframe(table_rows, use_container_width=True)
                else:
                    st.write("Results (raw):")
                    st.json(items)

        if show_debug:
            st.divider()
            st.subheader("Diagnostics")
            diag = result.get("diagnostics") or {}
            st.json(diag)


