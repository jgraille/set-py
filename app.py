from dash import Dash, dcc, html, Input, Output, State, callback, dash_table
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from io import StringIO
from bmrs_elexon import IndicatedImbalance, SolarWindForecastActuals

app = Dash()
# ------------------------ loading ------------------------
# Get selected data from IndicatedImbalance
s_date = '2025-11-20'
indicated_forecast = IndicatedImbalance(settlement_date=s_date)
df = indicated_forecast.get_data()
# Get current data from IndicatedImbalance
indicated_forecast = IndicatedImbalance()
df_current = indicated_forecast.get_data()
# Get current data from SolarWindForecastActuals
solar_wind = SolarWindForecastActuals(settlement_date=s_date)
solar, wind, solar_delta, wind_delta = solar_wind.get_data()  # Returns tuple: (merged_solar_df, merged_wind_df)
# ----------------------------------------------------------

# -------------- IndicatedImbalance Figures ----------------
# Calculate common y-axis range for both plots with extra margin
all_values = pd.concat([df['IndicatedImbalance'], df_current['IndicatedImbalance']])
y_min = all_values.min()
y_max = all_values.max()
margin = (y_max - y_min) * 0.1  # 10% margin
y_max = y_max + margin

# Create figures with same y-axis range (but independent x-axis)
fig1 = px.line(df, x='StartTime', y='IndicatedImbalance', title=f'Historical Forecast ({s_date})', markers=True)
fig1.update_yaxes(range=[y_min, y_max])

# Initial construction of fig2 to match callback structure (Current vs Previous)
last_update_time_init = df_current['PublishTime'].max().strftime('%H:%M:%S') if not df_current.empty else "N/A"
fig2 = go.Figure()

# Trace 1: Current Data
fig2.add_trace(go.Scatter(
    x=df_current['StartTime'], 
    y=df_current['IndicatedImbalance'],
    mode='lines+markers',
    name=f'Current (updated {last_update_time_init})',
    line=dict(color='blue'),
    hovertext=df_current['PublishTime'].astype(str)
))

# Trace 2: Previous Data (Initially same as Current for immediate visualization)
# We simulate "Previous" as the current state at startup since we have no history yet.
fig2.add_trace(go.Scatter(
    x=df_current['StartTime'], 
    y=df_current['IndicatedImbalance'],
    mode='lines',
    name='Previous (init state)',
    line=dict(color='gray', dash='dot'),
    hoverinfo='skip'
))

fig2.update_layout(
    title=f'Current Date Forecast: last update: {last_update_time_init}',
    xaxis_title='StartTime',
    yaxis_title='IndicatedImbalance',
    yaxis_range=[y_min, y_max]
)
# ----------------------------------------------------------

# ------------------ Wind & Solar Figures ------------------
# wind and solar are DataFrames with ForecastQuantity, ActualQuantity, StartTime, Delta
fig3 = go.Figure()

# Trace 1: Solar Forecast
fig3.add_trace(go.Scatter(
    x=solar['StartTime'],
    y=solar['ForecastQuantity'],
    mode='lines',
    name='Solar Forecast',
    line=dict(color='blue')
))
# Trace 2: Solar Actuals
fig3.add_trace(go.Scatter(
    x=solar['StartTime'],
    y=solar['ActualQuantity'],
    mode='lines+markers',
    name='Solar Actuals',
    line=dict(color='green')
))

fig3.update_layout(
    title=f'Solar Generation ({s_date})',
    xaxis_title='Time',
    yaxis_title='Quantity (MW)'
)

fig4 = go.Figure()

# Trace 1: Wind Forecast
fig4.add_trace(go.Scatter(
    x=wind['StartTime'],
    y=wind['ForecastQuantity'],
    mode='lines',
    name='Wind Forecast',
    line=dict(color='blue')
))
# Trace 2: Wind Actuals
fig4.add_trace(go.Scatter(
    x=wind['StartTime'],
    y=wind['ActualQuantity'],
    mode='lines+markers',
    name='Wind Actuals',
    line=dict(color='green')
))

fig4.update_layout(
    title=f'Wind Generation ({s_date})',
    xaxis_title='Time',
    yaxis_title='Quantity (MW)'
)
# ---------------------------

app.layout = html.Div([
    html.H1('Indicated Imbalance (surplus/shortage)'),
    dcc.Store(id='previous-data-store', data=df_current.to_json(date_format='iso', orient='split')), # Init store
    dcc.Graph(figure=fig1),
    dcc.Graph(id='current-forecast-graph', figure=fig2),
    dcc.Interval(
        id='interval-component',
        interval=10*60*1000, # in milliseconds ( 10 mins)
        n_intervals=0
    ),
    html.H1('Wind & Solar: Forecast vs Actuals'),
    dcc.Graph(figure=fig3),
    html.H3('Solar Delta (Forecast - Actual) by Settlement Period', style={'textAlign': 'center', 'marginTop': '20px'}),
    html.Div([
        dash_table.DataTable(
            data=solar_delta.to_dict('records'),
            columns=[{"name": str(i), "id": str(i)} for i in solar_delta.columns],
            style_table={'overflowX': 'auto', 'maxWidth': '95%', 'margin': '0 auto'},
            style_cell={'textAlign': 'center', 'minWidth': '50px', 'maxWidth': '70px', 'padding': '8px'},
            style_header={'backgroundColor': 'rgb(230, 230, 230)', 'fontWeight': 'bold'},
            style_data={'fontSize': '12px'}
        ) # llm + https://dash.plotly.com/datatable
    ], style={'marginBottom': '30px'}),
    dcc.Graph(figure=fig4),
    html.H3('Wind Delta (Forecast - Actual) by Settlement Period', style={'textAlign': 'center', 'marginTop': '20px'}),
    html.Div([
        dash_table.DataTable(
            data=wind_delta.to_dict('records'),
            columns=[{"name": str(i), "id": str(i)} for i in wind_delta.columns],
            style_table={'overflowX': 'auto', 'maxWidth': '95%', 'margin': '0 auto'},
            style_cell={'textAlign': 'center', 'minWidth': '50px', 'maxWidth': '70px', 'padding': '8px'},
            style_header={'backgroundColor': 'rgb(230, 230, 230)', 'fontWeight': 'bold'},
            style_data={'fontSize': '12px'}
        ) 
    ], style={'marginBottom': '30px'}),
])

@callback(
    [Output('current-forecast-graph', 'figure'),Output('previous-data-store', 'data')],
    [Input('interval-component', 'n_intervals')],
    [State('previous-data-store', 'data')],
    prevent_initial_call=True
)
def update_graph_live(n, previous_data_json):
    indicated_forecast = IndicatedImbalance()
    df_current = indicated_forecast.get_data()
    
    # Reconstruct previous data from store
    df_prev = pd.read_json(StringIO(previous_data_json), orient='split')
    df_prev['StartTime'] = pd.to_datetime(df_prev['StartTime'])
    df_prev['PublishTime'] = pd.to_datetime(df_prev['PublishTime'])

    # Check if data has actually changed by comparing max PublishTime
    current_max_pub = df_current['PublishTime'].max()
    prev_max_pub = df_prev['PublishTime'].max()
    
    # --- DEBUG LOGS ---
    print(f"\n--- Refresh triggered at {pd.Timestamp.now()} ---")
    print(f"Current Max PublishTime: {current_max_pub}")
    print(f"Previous Max PublishTime: {prev_max_pub}")
    
    # Determine if we have new data
    has_new_data = (current_max_pub != prev_max_pub)
    
    if has_new_data:
        print(">> New data detected! Updating previous to old current.")
        # Update store: current becomes the new "previous" for next time
        store_data = df_current.to_json(date_format='iso', orient='split')
    else:
        print(">> No new data from API yet. Keeping previous unchanged.")
        # Keep the old store unchanged
        store_data = previous_data_json
    # ------------------

    # Update Line Chart with TWO traces: Current vs Previous
    # Here I assume that the API might not push the same PublishTime for each period.
    last_update_time = df_current['PublishTime'].max().strftime('%H:%M:%S')
    prev_update_time = df_prev['PublishTime'].max().strftime('%H:%M:%S')
    
    fig = go.Figure()
    
    # Trace 1: Current Data
    if not df_current.empty:
        fig.add_trace(go.Scatter(
            x=df_current['StartTime'], 
            y=df_current['IndicatedImbalance'],
            mode='lines+markers',
            name=f'Current (updated {last_update_time})',
            line=dict(color='blue', width=2),
            hovertext=df_current['PublishTime'].astype(str)
        ))
        
    # Trace 2: Previous Data (from store)
    if not df_prev.empty:
        fig.add_trace(go.Scatter(
            x=df_prev['StartTime'], 
            y=df_prev['IndicatedImbalance'],
            mode='lines',
            name=f'Previous (updated {prev_update_time})',
            line=dict(color='gray', dash='dot', width=2),
            hovertext=df_prev['PublishTime'].astype(str)
        ))

    fig.update_layout(
        title=f'Current Date Forecast: last update: {last_update_time}',
        xaxis_title='StartTime',
        yaxis_title='IndicatedImbalance'
    )
    
    return fig, store_data

if __name__ == '__main__':
    app.run(debug=True)
