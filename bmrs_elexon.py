from abc import ABC, abstractmethod
from datetime import datetime
from io import BytesIO
from pandas import DataFrame
from pandas._libs.tslibs.timedeltas import Timedelta
from pandas.core.series import Series 
from requests import Response
import requests
import pandas as pd

class BmrsElexon(ABC):
    """
    BmrsElexon allows to requests various api endpoints
    from the Elexon organisation managing electricity market in the UK.

    Rate Limiting
    The Insights API is rated limited at 5k requests/min.
    https://bmrs.elexon.co.uk/api-documentation/guidance
    """
    @abstractmethod
    def get_data(self):
        pass

class IndicatedImbalance(BmrsElexon):
    """
    IndicatedImbalance allows to pull the last available forecasted `IndicatedImbalance`
    for the specified settlement date and all the periods of the day including 2 periods of the previous day.

    A period is a 30 minutes interval. 
    So for instance pulling period=1 will return values for 00:00:00Z 
    (which is the beginning of the day)

    """
    def __init__(self, settlement_date: str = None):
        """
        Create a new IndicatedImbalance instance with an optional settlement date.
        Args:
            settlement_date: str
        """
        if settlement_date is None:
            self.settlement_date: str = datetime.now().strftime('%Y-%m-%d')
        else:
            self.settlement_date: str = settlement_date
        self.url: str = f"https://data.elexon.co.uk/bmrs/api/v1/forecast/indicated/day-ahead/evolution?"
        self.periods: dict[str, list[int]] = {'previous': [47,48], 'selected': list(range(1,47))}


    def get_raw_data(self, settlement_date: str,settlement_period: int) -> DataFrame:
        """
        Pulls and returns a DataFrame with the following columns

        The returned DataFrame contains several rows with value estimation published 
        and revised every 30 min.
        Args:
            settlement_date: str
            settlement_period: int
        Returns:
            a DataFrame
        """
        try:
            params: dict = {
                "settlementDate": settlement_date,
                "settlementPeriod": settlement_period,
                "format": "csv"
            }
            response: Response = requests.get(self.url,params=params)
            response.raise_for_status()
            df: DataFrame = pd.read_csv(BytesIO(response.content))
            return df

        except requests.exceptions.RequestException as e:
            print(f"IndicatedImbalance - get_raw_data error: {e}")
            return DataFrame()

    @staticmethod
    def get_last_published_item(df: DataFrame) -> DataFrame:
        """
        Retrieve the last `PublishTime` row from the `IndicatedImbalance` DataFrame.
        Args:
            df: DataFrame
        Returns:
            a DataFrame (single row)
        """
        df['PublishTime']: Series = pd.to_datetime(df['PublishTime']).dt.tz_convert('Europe/Warsaw')
        return df.loc[[df['PublishTime'].idxmax()]]

    def get_data(self) -> DataFrame:
        """
        Build a dataset of `PublishTime`,`StartTime` and `IndicatedImbalance`
        Make:
         - timezone conversion,
         - for any period, pick up the latest published row
         - safety sort on the subset
         - checking time frequency is approximately 30 minutes (tolerance: ±3 minutes)
        Args:
            df: pd.DataFrame
        Returns:
            a DataFrame
        """

        previous_settlement_date: str = (pd.to_datetime(self.settlement_date) - pd.Timedelta(days=1)).strftime('%Y-%m-%d')
        list_df: list[DataFrame] = []

        for period in self.periods['previous']:
            df: DataFrame = self.get_raw_data(previous_settlement_date,period)
            if not df.empty:
                last_published_item: DataFrame = self.get_last_published_item(df)
                list_df.append(last_published_item)
        for period in self.periods['selected']:
            df: DataFrame = self.get_raw_data(self.settlement_date,period)
            if not df.empty:
                last_published_item: DataFrame = self.get_last_published_item(df)
                list_df.append(last_published_item)

        if not list_df:
            return DataFrame()

        df: DataFrame = pd.concat(list_df, ignore_index=True)

        # need for time zone conversion for the `StartTime`
        df['StartTime']: Series = pd.to_datetime(df['StartTime']).dt.tz_convert('Europe/Warsaw')
        
        # safety sort on the subset
        df.sort_values(by='StartTime', inplace=True)

        # checking time frequency is approximately 30 minutes (tolerance: ±3 minutes)
        if len(df) > 1:
            time_diffs: Series = df['StartTime'].diff().dropna()
            expected_diff: Timedelta = pd.Timedelta(minutes=30)
            invalid_diffs: Series = time_diffs[abs(time_diffs - expected_diff) > pd.Timedelta(minutes=3)]            
            if not invalid_diffs.empty:
                # Check if more than 5% of intervals are invalid
                invalid_ratio = len(invalid_diffs) / len(time_diffs)
                if invalid_ratio > 0.05:
                    raise ValueError(
                        f"Time sequence must have ~30-minute frequency (±3min tolerance) for at least 95% of intervals. "
                        f"Found {invalid_ratio*100:.1f}% invalid intervals."
                    )
        return df[['PublishTime','StartTime', 'IndicatedImbalance']]

