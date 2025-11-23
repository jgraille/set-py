import pytest
import pandas as pd
import requests
from datetime import datetime
from unittest.mock import Mock, patch
from bmrs_elexon import IndicatedImbalance

# LLM generated, reviewed by human

# Path to test data
TEST_DATA_PATH = "data/response_48.csv"


class TestIndicatedImbalance:

    # --- constructor ---
    def test_init_with_default_date(self):
        forecast = IndicatedImbalance()
        today = datetime.now().strftime('%Y-%m-%d')
        assert forecast.settlement_date == today

    def test_init_with_explicit_date(self):
        forecast = IndicatedImbalance(settlement_date='2025-11-11')
        assert forecast.settlement_date == '2025-11-11'

    # --- get_raw_data() ---
    @patch('bmrs_elexon.requests.get')
    def test_get_raw_data_success(self, mock_get):
        # Load real CSV data from test file
        with open(TEST_DATA_PATH, 'rb') as f:
            csv_data = f.read()
        
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = csv_data
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        forecast = IndicatedImbalance(settlement_date='2025-11-11')
        # Test raw data fetching for a single period
        df = forecast.get_raw_data('2025-11-11', 48)

        assert not df.empty
        assert len(df) == 71  # Based on response_48.csv
        assert 'PublishTime' in df.columns
        mock_get.assert_called_once()

    @patch('bmrs_elexon.requests.get')
    def test_get_raw_data_api_error(self, mock_get):
        mock_get.side_effect = requests.exceptions.RequestException("API error")
        
        forecast = IndicatedImbalance(settlement_date='2025-11-11')
        df = forecast.get_raw_data('2025-11-11', 48)

        assert df.empty
        assert isinstance(df, pd.DataFrame)

    # --- get_last_published_item() ---
    def test_get_last_published_item(self):
        df = pd.read_csv(TEST_DATA_PATH)
        
        # Call static method
        last_item = IndicatedImbalance.get_last_published_item(df)
        
        assert isinstance(last_item, pd.DataFrame)
        assert len(last_item) == 1
        
        # Check it picked the row with max PublishTime
        # We compare the original value (before timezone conversion inside method)
        # Identify the expected row in input df
        df['PublishTime_dt'] = pd.to_datetime(df['PublishTime'])
        expected_idx = df['PublishTime_dt'].idxmax()
        expected_imbalance = df.loc[expected_idx, 'IndicatedImbalance']
        
        assert last_item['IndicatedImbalance'].iloc[0] == expected_imbalance

    # --- get_data() ---
    @patch.object(IndicatedImbalance, 'get_raw_data')
    def test_get_data_logic_flow(self, mock_get_raw):
        # Mock get_raw_data to return valid data for a few calls
        start_time = pd.Timestamp('2025-11-11 00:00:00').tz_localize('Europe/Warsaw')
        
        def side_effect(date, period):
            # Simulation for ONE specific period (e.g. period 1, 2...)
            # StartTime is FIXED for this period
            offset_min = (period - 1) * 30
            period_start_time = start_time + pd.Timedelta(minutes=offset_min)
            start_time_str = period_start_time.tz_convert('UTC').isoformat()
            
            # PublishTime VARIES (history of updates for this period)
            # We simulate 2 updates spaced by 30 minutes (typical BMRS cycle)
            # e.g. update 1 is 60 min before delivery, update 2 is 30 min before
            publish_time_1 = (period_start_time - pd.Timedelta(minutes=60)).tz_convert('UTC').isoformat()
            publish_time_2 = (period_start_time - pd.Timedelta(minutes=30)).tz_convert('UTC').isoformat() # Latest
            
            data = {
                'PublishTime': [publish_time_1, publish_time_2], 
                'StartTime': [start_time_str, start_time_str], # Fixed for this period
                'SettlementDate': [date, date],
                'SettlementPeriod': [period, period],
                'Boundary': ['N', 'N'],
                'IndicatedGeneration': [20000, 22000 + period * 10],
                'IndicatedDemand': [-13000, -13000 - period * 10],
                'IndicatedMargin': [38000, 39000 + period * 10],
                'IndicatedImbalance': [50, 100.0 * period] # We expect the last one
            }
            # print(data)
            return pd.DataFrame(data)

        mock_get_raw.side_effect = side_effect

        forecast = IndicatedImbalance(settlement_date='2025-11-11')
        # Override periods to test a small subset (e.g. 1, 2, 3) to avoid 48 calls
        forecast.periods = {'previous': [], 'selected': [1, 2, 3]} 
        
        df_result = forecast.get_data()

        # Check aggregation
        assert len(df_result) == 3
        assert 'PublishTime' in df_result.columns
        assert 'StartTime' in df_result.columns
        assert 'IndicatedImbalance' in df_result.columns
        
        # Verify time diffs
        times = df_result['StartTime'].sort_values()
        diffs = times.diff().dropna()
        assert all(diffs == pd.Timedelta(minutes=30))

    @patch.object(IndicatedImbalance, 'get_raw_data')
    def test_get_data_frequency_check_error(self, mock_get_raw):
        # Simulate data with INVALID frequency (e.g. 60 min gaps)
        start_time = pd.Timestamp('2025-11-11 00:00:00').tz_localize('Europe/Warsaw')
        
        def side_effect(date, period):
            # period 1 -> 0 min, period 2 -> 60 min (skip 30)
            offset_min = (period - 1) * 60 
            current_time = start_time + pd.Timedelta(minutes=offset_min)
            utc_time_str = current_time.tz_convert('UTC').isoformat()
            
            data = {
                'PublishTime': [utc_time_str],
                'StartTime': [utc_time_str],
                'SettlementDate': [date],
                'SettlementPeriod': [period],
                'IndicatedImbalance': [100]
            }
            return pd.DataFrame(data)

        mock_get_raw.side_effect = side_effect

        forecast = IndicatedImbalance(settlement_date='2025-11-11')
        forecast.periods = {'previous': [], 'selected': [1, 2, 3]}
        
        # Expect ValueError because > 5% intervals are bad (here 100% are 60min)
        with pytest.raises(ValueError, match="Time sequence must have ~30-minute frequency"):
            forecast.get_data()
