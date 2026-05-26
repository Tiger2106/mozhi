"""Fix the 2 failing tests by using fetchall.side_effect instead of fetchall.return_value."""

path = r'C:\Users\17699\mozhi_platform\src\backtest\analysis\ingest\tests\test_ingest_analysis.py'

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# --- Fix 1: test_qa_report_overall_status_warn_on_deviation ---
old1 = '''    @patch("src.backtest.analysis.ingest.writer.sqlite3.connect")
    def test_qa_report_overall_status_warn_on_deviation(self, mock_connect):
        """有偏差时 overall_status 为 WARN"""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            _make_db_row(table_name="analysis_meta", cnt=1),
            _make_db_row(table_name="analysis_metrics_core", cnt=1),
            _make_db_row(table_name="analysis_metrics_ext", cnt=0),
            _make_db_row(table_name="analysis_docs", cnt=1),
            _make_db_row(table_name="schema_version", cnt=1),
        ]

        writer = Writer(":memory:", tempfile.mkdtemp(), logger=logging.getLogger("test_qa"))
        input_data = _make_input(run_id="r1", n_core=1, n_ext=0, n_docs=1)
        input_data.metrics_core[0].total_return_pct = 150.0

        result = writer._generate_qa_report(input_data, 42, None)

        # 行数据匹配 + 外键 PASS, 但偏差是 WARN → 整体 WARN
        assert result.overall_status in ("WARN", "PASS")'''

new1 = '''    @patch("src.backtest.analysis.ingest.writer.sqlite3.connect")
    def test_qa_report_overall_status_warn_on_deviation(self, mock_connect):
        """有偏差时 overall_status 为 WARN"""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        # Use side_effect: first fetchall() = row counts, second fetchall() = FK check (empty = no mismatches)
        row_count_data = [
            _make_db_row(table_name="analysis_meta", cnt=1),
            _make_db_row(table_name="analysis_metrics_core", cnt=1),
            _make_db_row(table_name="analysis_metrics_ext", cnt=0),
            _make_db_row(table_name="analysis_docs", cnt=1),
            _make_db_row(table_name="schema_version", cnt=1),
        ]
        mock_conn.execute.return_value.fetchall.side_effect = [row_count_data, []]

        writer = Writer(":memory:", tempfile.mkdtemp(), logger=logging.getLogger("test_qa"))
        input_data = _make_input(run_id="r1", n_core=1, n_ext=0, n_docs=1)
        input_data.metrics_core[0].total_return_pct = 150.0

        result = writer._generate_qa_report(input_data, 42, None)

        # 行数据匹配 + 外键 PASS, 但偏差是 WARN → 整体 WARN
        assert result.overall_status in ("WARN", "PASS")'''

assert old1 in content, 'Fix 1: old text not found'
content = content.replace(old1, new1, 1)
print('Fix 1 applied')

# --- Fix 2: test_qa_report_schema_version_check ---
old2 = '''        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        mock_conn.execute.return_value.fetchall.return_value = [
            _make_db_row(table_name="analysis_meta", cnt=1),
            _make_db_row(table_name="analysis_metrics_core", cnt=1),
            _make_db_row(table_name="analysis_metrics_ext", cnt=0),
            _make_db_row(table_name="analysis_docs", cnt=1),
            _make_db_row(table_name="schema_version", cnt=1),
        ]

        writer = Writer(":memory:", tempfile.mkdtemp(), logger=logging.getLogger("test_qa"))
        result = writer._generate_qa_report(_make_input(run_id="r1"), 42, None)

        sv_check = [c for c in result.checks if c.check_id == "row_count_schema_version"]
        assert len(sv_check) == 1
        assert sv_check[0].status == "PASS"'''

new2 = '''        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        # Use side_effect: first fetchall() = row counts, second fetchall() = FK check (empty = no mismatches)
        row_count_data = [
            _make_db_row(table_name="analysis_meta", cnt=1),
            _make_db_row(table_name="analysis_metrics_core", cnt=1),
            _make_db_row(table_name="analysis_metrics_ext", cnt=0),
            _make_db_row(table_name="analysis_docs", cnt=1),
            _make_db_row(table_name="schema_version", cnt=1),
        ]
        mock_conn.execute.return_value.fetchall.side_effect = [row_count_data, []]

        writer = Writer(":memory:", tempfile.mkdtemp(), logger=logging.getLogger("test_qa"))
        result = writer._generate_qa_report(_make_input(run_id="r1"), 42, None)

        sv_check = [c for c in result.checks if c.check_id == "row_count_schema_version"]
        assert len(sv_check) == 1
        assert sv_check[0].status == "PASS"'''

assert old2 in content, 'Fix 2: old text not found'
content = content.replace(old2, new2, 1)
print('Fix 2 applied')

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print('All fixes applied successfully')
