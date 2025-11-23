import pandas as pd
import requests
from datetime import datetime
from unittest.mock import Mock, patch
from bmrs_elexon import SolarWindForecastActuals

# LLM generated, reviewed by human

# Path to test data
TEST_DATA_PATH = "data/windsolarforecastctuals.csv"

class TestSolarWindForecastActuals:

    # --- constructor ---
    def test_init_with_explicit_date(self):
        forecast = SolarWindForecastActuals(settlement_date='2025-11-20')
        assert forecast.settlement_date == '2025-11-20'

    # --- get_raw_data() ---
    @patch('bmrs_elexon.requests.get')
    def test_get_raw_data_success(self, mock_get):
        # Load real CSV data from test file (forecast data)
        with open(TEST_DATA_PATH, 'rb') as f:
            csv_data = f.read()
        
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = csv_data
        mock_response.raise_for_status = Mock() # 'went ok'
        mock_get.return_value = mock_response

        forecast = SolarWindForecastActuals(settlement_date='2025-11-20')
        # Test raw data fetching for a single period
        df = forecast.get_raw_data(forecast.forecast_url, forecast.forecast_params)

        # Verify content matches expected data from CSV
        expected_df = pd.read_csv(TEST_DATA_PATH)
        pd.testing.assert_frame_equal(df, expected_df)
        
        mock_get.assert_called_once()

    @patch('bmrs_elexon.requests.get')
    def test_get_raw_data_api_error(self, mock_get):
        mock_get.side_effect = requests.exceptions.RequestException("API error")
        
        forecast = SolarWindForecastActuals(settlement_date='2025-11-20')
        df = forecast.get_raw_data(forecast.forecast_url, forecast.forecast_params)

        assert df.empty
        assert isinstance(df, pd.DataFrame)

    # --- get_data() ---
    def test_get_data(self):
        forecast = SolarWindForecastActuals(settlement_date='2025-11-20')
        forecast.get_data()
