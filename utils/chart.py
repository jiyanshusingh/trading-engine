import plotly.graph_objects as go


def create_chart(df):

    fig = go.Figure()

    # Candlestick
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["Open"],
            high=df["High"],
            low=df["Low"],
            close=df["Close"],
            name="Price"
        )
    )

    # EMA 20
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["EMA20"],
            name="EMA20",
            line=dict(width=2)
        )
    )

    # EMA 50
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["EMA50"],
            name="EMA50",
            line=dict(width=2)
        )
    )

    # EMA 200
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["EMA200"],
            name="EMA200",
            line=dict(width=2)
        )
    )

    fig.update_layout(
        height=700,
        xaxis_rangeslider_visible=False,
        template="plotly_dark",
        title="Price Chart"
    )

    return fig