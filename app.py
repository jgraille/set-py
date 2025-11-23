from dash import Dash, dcc, html, Input, Output, State, callback
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from bmrs_elexon import IndicatedImbalance

app = Dash()
# Get selected data from IndicatedImbalance
s_date = '2025-11-20'
indicated_forecast = IndicatedImbalance(settlement_date=s_date)
df = indicated_forecast.get_data()
# Get current data from IndicatedImbalance
indicated_forecast = IndicatedImbalance()
df_current = indicated_forecast.get_data()

# Calculate common y-axis range for both plots with extra margin
all_values = pd.concat([df['IndicatedImbalance'], df_current['IndicatedImbalance']])
y_min = all_values.min()
y_max = all_values.max()
margin = (y_max - y_min) * 0.1  # 10% margin
y_max = y_max + margin

# Create figures with same y-axis range (but independent x-axis)
fig1 = px.line(df, x='StartTime', y='IndicatedImbalance', title=f'Historical Forecast ({s_date})')
fig1.update_yaxes(range=[y_min, y_max])

# Initial construction of fig2 to match callback structure (Current vs Previous)
last_update_time_init = df_current['PublishTime'].max().strftime('%H:%M:%S') if not df_current.empty else "N/A"
fig2 = go.Figure()

if not df_current.empty:
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

app.layout = html.Div([
    html.H1('Indicated Forecast'),
    dcc.Store(id='previous-data-store', data=df_current.to_json(date_format='iso', orient='split')), # Init store
    dcc.Graph(figure=fig1),
    dcc.Graph(id='current-forecast-graph', figure=fig2),
    dcc.Interval(
        id='interval-component',
        interval=10*60*1000, # in milliseconds (10 mins)
        n_intervals=0
    )
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
    df_prev = pd.read_json(previous_data_json, orient='split')
    df_prev['StartTime'] = pd.to_datetime(df_prev['StartTime'])

    # --- DEBUG LOGS ---
    current_max_pub = df_current['PublishTime'].max() if not df_current.empty else "None"
    prev_max_pub = df_prev['PublishTime'].max() if not df_prev.empty and 'PublishTime' in df_prev.columns else "None"
    
    print(f"\n--- Refresh triggered at {pd.Timestamp.now()} ---")
    print(f"Current Max PublishTime: {current_max_pub}")
    print(f"Previous Max PublishTime: {prev_max_pub}")
    
    is_same = df_current.equals(df_prev)
    if is_same:
        print(">> No new data from API yet. Curves will remain identical.")
    else:
        print(">> New data detected! Curves should diverge.")
    # ------------------

    # Update Line Chart with TWO traces: Current vs Previous
    # Here I assume that the API might not push the same PublishTime for each period.
    last_update_time = df_current['PublishTime'].max().strftime('%H:%M:%S') if not df_current.empty else "N/A"
    
    fig = go.Figure()
    
    # Trace 1: Current Data
    if not df_current.empty:
        fig.add_trace(go.Scatter(
            x=df_current['StartTime'], 
            y=df_current['IndicatedImbalance'],
            mode='lines+markers',
            name=f'Current (updated {last_update_time})',
            line=dict(color='blue'),
            hovertext=df_current['PublishTime'].astype(str)
        ))
        
    # Trace 2: Previous Data (from store)
    if not df_prev.empty:
        fig.add_trace(go.Scatter(
            x=df_prev['StartTime'], 
            y=df_prev['IndicatedImbalance'],
            mode='lines',
            name='Previous (last update)',
            line=dict(color='gray', dash='dot'),
            hovertext=df_prev['PublishTime'].astype(str)
        ))

    fig.update_layout(
        title=f'Current Date Forecast: last update: {last_update_time}',
        xaxis_title='StartTime',
        yaxis_title='IndicatedImbalance'
    )
    
    # Update store with new data
    store_data = df_current.to_json(date_format='iso', orient='split')
    
    return fig, store_data

if __name__ == '__main__':
    app.run(debug=True)
