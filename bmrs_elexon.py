from abc import ABC, abstractmethod
from datetime import datetime
from io import BytesIO
from pandas import DataFrame
from pandas._libs.tslibs.timedeltas import Timedelta
from pandas.core.series import Series 
from requests import Response
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

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
        Fetch from api endpoint

        The returned DataFrame has the following columns:
        PublishTime,StartTime,SettlementDate,SettlementPeriod,Boundary,
        IndicatedGeneration,IndicatedDemand,IndicatedMargin,IndicatedImbalance

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
        
        Uses parallel API calls for performance.
        
        Returns:
            a DataFrame
        """
        previous_settlement_date: str = (pd.to_datetime(self.settlement_date) - pd.Timedelta(days=1)).strftime('%Y-%m-%d')
        
        # Helper function to fetch and process a single period
        def fetch_period(settlement_date: str, period: int) -> DataFrame:
            df = self.get_raw_data(settlement_date, period)
            if not df.empty:
                return self.get_last_published_item(df)
            return DataFrame()
        
        # Prepare all tasks (date, period pairs)
        tasks = []
        for period in self.periods['previous']:
            tasks.append((previous_settlement_date, period))
        for period in self.periods['selected']:
            tasks.append((self.settlement_date, period))
        
        # Execute all API calls in parallel (max 20 workers to respect API rate limits)
        list_df: list[DataFrame] = []
        with ThreadPoolExecutor(max_workers=20) as executor:
            # Submit all tasks
            future_to_period = {executor.submit(fetch_period, date, period): (date, period) 
                                for date, period in tasks}
            
            # Collect results as they complete
            for future in as_completed(future_to_period):
                result = future.result()
                if not result.empty:
                    list_df.append(result)
        
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

class SolarWindForecastActuals(BmrsElexon):

    def __init__(self, settlement_date: str):
        """
        Create a new SolarWindForecastActuals instance with a settlement date.
        Args:
            settlement_date: str
        """
        self.settlement_date: str = settlement_date
        self.settlement_period_from: int = 1
        self.settlement_period_to: int = 48
        self.actuals_url: str = f"https://data.elexon.co.uk/bmrs/api/v1/generation/actual/per-type/wind-and-solar?"
        self.forecast_url: str = f"https://data.elexon.co.uk/bmrs/api/v1/forecast/generation/wind-and-solar/day-ahead?"
        self.actuals_params: dict = {
            "from": self.settlement_date,
            "to": self.settlement_date,
            "settlementPeriodFrom": self.settlement_period_from,
            "settlementPeriodTo": self.settlement_period_to,
            "format": "csv"
        }
        self.forecast_params = self.actuals_params.copy()
        self.forecast_params["processType"] = "day ahead"
        
    def get_raw_data(self, url: str, params: dict) -> DataFrame:
        """
        Fetch from api endpoint
        Pulls and returns a DataFrame with the following columns

        The returned DataFrame has the following columns:
        PublishTime,ProcessType,BusinessType,PsrType,StartTime,SettlementDate,SettlementPeriod,Quantity
        Args:
            url: str
            params: dict
        Returns:
            a DataFrame
        """
        try:
            response: Response = requests.get(url, params)
            response.raise_for_status()
            df: DataFrame = pd.read_csv(BytesIO(response.content))
            return df

        except requests.exceptions.RequestException as e:
            print(f"SolarWindForecastActuals - get_raw_data error: {e}")
            return DataFrame()


    def get_data(self) -> tuple:
        """
        Fetch and process wind and solar forecast/actuals data.
        
        Computes forecast, actuals, and delta (forecast - actual) by settlement period.
        
        Returns:
            a dict of lists of DataFrames
        """
        # -------------------------------- forecast --------------------------------
        # Fetch
        ft: DataFrame = self.get_raw_data(self.forecast_url, self.forecast_params)
        
        # CEST conversion
        ft['StartTime']: Series = pd.to_datetime(ft['StartTime']).dt.tz_convert('Europe/Warsaw')
        
        # Split into Solar and Wind DataFrames
        ft_solar: DataFrame = ft[ft['BusinessType'] == 'Solar generation'].copy()
        ft_wind: DataFrame = ft[ft['BusinessType'] == 'Wind generation'].copy()
        del ft
        
        # For Wind: sum Quantity by SettlementPeriod (combines Wind Onshore + Wind Offshore)
        ft_wind: DataFrame = ft_wind.groupby(['StartTime', 'SettlementPeriod'],as_index=False)['Quantity'].sum()
        
        # -------------------------------- actuals --------------------------------
        # Fetch
        at: DataFrame = self.get_raw_data(self.actuals_url, self.actuals_params)
        
        # CEST conversion
        at['StartTime']: Series = pd.to_datetime(at['StartTime']).dt.tz_convert('Europe/Warsaw')
        
        # Split into Solar and Wind DataFrames
        at_solar: DataFrame = at[at['BusinessType'] == 'Solar generation'].copy()
        at_wind: DataFrame = at[at['BusinessType'] == 'Wind generation'].copy()
        del at

        # For Wind: sum Quantity by SettlementPeriod (combines Wind Onshore + Wind Offshore)
        at_wind: DataFrame = at_wind.groupby(['StartTime', 'SettlementPeriod'],as_index=False)['Quantity'].sum()

        # -------------------------------- adding delta columns--------------------------------
        # For Solar: merge forecast and actuals on SettlementPeriod, compute delta
        merged_solar = pd.merge(
            ft_solar[['SettlementPeriod', 'Quantity']].rename(columns={'Quantity': 'ForecastQuantity'}),
            at_solar[['StartTime', 'SettlementPeriod', 'Quantity',]].rename(columns={'Quantity': 'ActualQuantity'}),
            on='SettlementPeriod', how='inner')
        # A positive value will mean that forecast estimation was higher than the actual generation.
        merged_solar['Delta'] = merged_solar['ForecastQuantity'] - merged_solar['ActualQuantity']
        del ft_solar, at_solar

        merged_wind = pd.merge(
            ft_wind[['SettlementPeriod', 'Quantity']].rename(columns={'Quantity': 'ForecastQuantity'}),
            at_wind[['StartTime', 'SettlementPeriod', 'Quantity',]].rename(columns={'Quantity': 'ActualQuantity'}),
            on='SettlementPeriod', how='inner')
        # A positive value will mean that forecast estimation was higher than the actual generation.
        merged_wind['Delta'] = merged_wind['ForecastQuantity'] - merged_wind['ActualQuantity']
        del ft_wind, at_wind

        # Sort
        merged_solar.sort_values(by='SettlementPeriod', inplace=True)
        merged_wind.sort_values(by='SettlementPeriod', inplace=True)
        
        # Prepare delta tables (transposed: periods as columns)
        # Solar delta - transpose to wide format
        solar_delta_df = merged_solar[['SettlementPeriod', 'Delta']].copy()
        solar_delta_df['Delta'] = solar_delta_df['Delta'].round(2)
        solar_delta_wide = solar_delta_df.set_index('SettlementPeriod').T
        
        # Wind delta - transpose to wide format
        wind_delta_df = merged_wind[['SettlementPeriod', 'Delta']].copy()
        wind_delta_df['Delta'] = wind_delta_df['Delta'].round(2)
        wind_delta_wide = wind_delta_df.set_index('SettlementPeriod').T
        
        # -------------------------------- return --------------------------------
        return merged_solar, merged_wind, solar_delta_wide, wind_delta_wide

