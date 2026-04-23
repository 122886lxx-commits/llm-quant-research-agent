import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List

from ....permissions import NETWORK
from ..base import BaseStep


class MarketBarsStep(BaseStep):
    async def execute(self, config: Dict[str, Any], context: Any) -> Dict[str, Any]:
        symbols = self._normalize_symbols(config.get("symbols"))
        lookback_days = int(config.get("lookback_days", 30))
        if lookback_days < 2:
            raise ValueError("data.market_bars requires lookback_days >= 2")

        grouped: Dict[str, List[Dict[str, Any]]] = {}
        live_symbols = [symbol for symbol in symbols if self._is_baostock_symbol(symbol)]
        fixture_symbols = [symbol for symbol in symbols if symbol not in live_symbols]

        if live_symbols:
            if context is not None and getattr(context, "permission_policy", None) is not None:
                context.permission_policy.require(
                    NETWORK,
                    "fetch live BaoStock market bars for {0}".format(", ".join(live_symbols)),
                )
            grouped.update(self._fetch_live_bars(live_symbols, lookback_days))
        if fixture_symbols:
            grouped.update(self._load_fixture_bars(fixture_symbols, lookback_days))

        return grouped

    def _normalize_symbols(self, raw_symbols: Any) -> List[str]:
        if isinstance(raw_symbols, str):
            symbols = [raw_symbols]
        elif isinstance(raw_symbols, list):
            symbols = [str(symbol).strip() for symbol in raw_symbols]
        else:
            raise ValueError("data.market_bars requires config.symbols to be a string or list of strings")

        normalized = [symbol for symbol in symbols if symbol]
        if not normalized:
            raise ValueError("data.market_bars requires at least one symbol")
        return normalized

    def _is_baostock_symbol(self, symbol: str) -> bool:
        return symbol.startswith(("sh.", "sz.", "bj."))

    def _fetch_live_bars(self, symbols: List[str], lookback_days: int) -> Dict[str, List[Dict[str, Any]]]:
        try:
            import baostock as bs
        except ImportError as exc:
            raise RuntimeError("BaoStock is required for exchange-prefixed symbols.") from exc

        start_date = (date.today() - timedelta(days=max(lookback_days * 3, lookback_days + 7))).strftime("%Y-%m-%d")
        end_date = date.today().strftime("%Y-%m-%d")
        login_result = bs.login()
        if login_result.error_code != "0":
            raise RuntimeError("BaoStock login failed: {0} {1}".format(login_result.error_code, login_result.error_msg))

        grouped: Dict[str, List[Dict[str, Any]]] = {}
        try:
            for symbol in symbols:
                grouped[symbol] = self._query_symbol(bs, symbol, start_date, end_date, lookback_days)
        finally:
            try:
                bs.logout()
            except Exception:
                pass
        return grouped

    def _query_symbol(self, bs: Any, symbol: str, start_date: str, end_date: str, lookback_days: int) -> List[Dict[str, Any]]:
        result = bs.query_history_k_data_plus(
            symbol,
            "date,code,close",
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="3",
        )
        if result.error_code != "0":
            raise RuntimeError("BaoStock query failed for {0}: {1} {2}".format(symbol, result.error_code, result.error_msg))

        series: List[Dict[str, Any]] = []
        while result.error_code == "0" and result.next():
            row = result.get_row_data()
            if len(row) >= 3 and row[2]:
                series.append({"date": row[0], "close": float(row[2])})

        series = series[-lookback_days:]
        if not series:
            raise ValueError("No daily bars returned for symbol '{0}'".format(symbol))
        return series

    def _load_fixture_bars(self, symbols: List[str], lookback_days: int) -> Dict[str, List[Dict[str, Any]]]:
        dataset_path = self._fixture_path()
        with open(dataset_path, "r", encoding="utf-8") as handle:
            dataset = json.load(handle)

        grouped: Dict[str, List[Dict[str, Any]]] = {}
        missing = []
        for symbol in symbols:
            series = dataset.get(symbol)
            if not isinstance(series, list) or not series:
                missing.append(symbol)
                continue
            grouped[symbol] = [
                {"date": item["date"], "close": float(item["close"])}
                for item in series[-lookback_days:]
                if "date" in item and "close" in item
            ]
        if missing:
            raise ValueError("Unsupported demo symbols without fixture data: {0}".format(", ".join(missing)))
        return grouped

    def _fixture_path(self) -> Path:
        env_path = os.getenv("QUANT_AGENT_FIXTURE_PATH")
        if env_path:
            return Path(env_path)
        for parent in Path(__file__).resolve().parents:
            candidate = parent / "datasets" / "daily_bars.json"
            if candidate.exists():
                return candidate
        raise FileNotFoundError("Could not locate datasets/daily_bars.json")
