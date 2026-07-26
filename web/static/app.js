// Initialize TradingView Lightweight Charts
document.addEventListener("DOMContentLoaded", () => {
    const mainContainer = document.getElementById("main-chart");
    const rsiContainer = document.getElementById("rsi-chart");

    // 1. Create Main Candlestick Chart
    const chart = LightweightCharts.createChart(mainContainer, {
        layout: {
            background: { type: 'solid', color: '#090B10' },
            textColor: '#8E9BAE',
            fontSize: 12,
            fontFamily: 'Inter, sans-serif',
        },
        grid: {
            vertLines: { color: 'rgba(255, 255, 255, 0.03)' },
            horzLines: { color: 'rgba(255, 255, 255, 0.03)' },
        },
        crosshair: {
            mode: LightweightCharts.CrosshairMode.Normal,
        },
        rightPriceScale: {
            borderColor: 'rgba(255, 255, 255, 0.08)',
        },
        timeScale: {
            borderColor: 'rgba(255, 255, 255, 0.08)',
            timeVisible: true,
            secondsVisible: false,
        },
    });

    // Candlestick Series
    const candleSeries = chart.addCandlestickSeries({
        upColor: '#00E676',
        downColor: '#FF1744',
        borderUpColor: '#00E676',
        borderDownColor: '#FF1744',
        wickUpColor: '#00E676',
        wickDownColor: '#FF1744',
    });

    // EMA Lines
    const ema9Series = chart.addLineSeries({ color: '#00E5FF', lineWidth: 2, title: 'EMA 9' });
    const ema21Series = chart.addLineSeries({ color: '#FFD600', lineWidth: 2, title: 'EMA 21' });

    // Price Lines (Entry, TP1, SL)
    candleSeries.createPriceLine({
        price: 65000.0,
        color: '#00E5FF',
        lineWidth: 2,
        lineStyle: LightweightCharts.LineStyle.Dashed,
        axisLabelVisible: true,
        title: 'ENTRY ($65,000)',
    });

    const tpLine = candleSeries.createPriceLine({
        price: 65450.0,
        color: '#00E676',
        lineWidth: 2,
        lineStyle: LightweightCharts.LineStyle.Solid,
        axisLabelVisible: true,
        title: 'TARGET TP1 ($65,450)',
    });

    const slLine = candleSeries.createPriceLine({
        price: 64650.0,
        color: '#FF1744',
        lineWidth: 2,
        lineStyle: LightweightCharts.LineStyle.Solid,
        axisLabelVisible: true,
        title: 'STOP LOSS ($64,650)',
    });

    // 2. Create RSI Subchart
    const rsiChart = LightweightCharts.createChart(rsiContainer, {
        layout: {
            background: { type: 'solid', color: '#090B10' },
            textColor: '#8E9BAE',
            fontSize: 11,
        },
        grid: {
            vertLines: { color: 'rgba(255, 255, 255, 0.02)' },
            horzLines: { color: 'rgba(255, 255, 255, 0.02)' },
        },
        rightPriceScale: { borderColor: 'rgba(255, 255, 255, 0.08)' },
        timeScale: { visible: false },
    });

    const rsiSeries = rsiChart.addLineSeries({ color: '#00E5FF', lineWidth: 2 });
    
    // RSI Overbought / Oversold Lines
    rsiSeries.createPriceLine({ price: 70, color: '#FF1744', lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dotted, title: 'OB 70' });
    rsiSeries.createPriceLine({ price: 30, color: '#00E676', lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dotted, title: 'OS 30' });

    // Sync TimeScales
    chart.timeScale().subscribeVisibleTimeRangeChange(timeRange => {
        rsiChart.timeScale().setVisibleTimeRange(timeRange);
    });

    // Fetch and Update Data Function
    async function updateDashboard() {
        try {
            const response = await fetch('/api/data');
            if (!response.ok) return;
            const data = await response.json();

            // Update Price & Stats UI
            if (data.btc_price) {
                document.getElementById('live-price').innerText = `$${data.btc_price.toLocaleString('en-US', { minimumFractionDigits: 2 })}`;
                document.getElementById('live-change').innerText = `${data.change_24h >= 0 ? '+' : ''}${data.change_24h.toFixed(2)}%`;
            }

            // Update UI based on Position Side
            if (data.position_side) {
                const pill = document.getElementById('trade-pill');
                const title = document.getElementById('pill-title');
                if (data.position_side === 'SHORT') {
                    pill.className = 'trade-pill short'; // You'd need a CSS class for short if you want red, else it stays default or you can add logic
                    pill.style.background = 'rgba(255, 23, 68, 0.1)';
                    pill.style.borderColor = 'rgba(255, 23, 68, 0.3)';
                    title.innerText = 'ACTIVE POSITION: SHORT';
                    title.style.color = '#FF1744';
                    
                    // Update chart lines colors for Short (TP is green but below, SL is red but above)
                    // The line positions are hardcoded in the JS init, but since we are simulating Short we update them
                    tpLine.applyOptions({ price: 64550.0, title: 'TARGET TP1 ($64,550)' });
                } else {
                    pill.className = 'trade-pill long';
                    pill.style.background = 'rgba(0, 230, 118, 0.1)';
                    pill.style.borderColor = 'rgba(0, 230, 118, 0.3)';
                    title.innerText = 'ACTIVE POSITION: LONG';
                    title.style.color = '#00E676';
                    tpLine.applyOptions({ price: 65450.0, title: 'TARGET TP1 ($65,450)' });
                }
            }

            if (data.tp_progress !== undefined) {
                document.getElementById('tp-progress-bar').style.width = `${data.tp_progress}%`;
                document.getElementById('tp-progress-text').innerText = `${data.tp_progress.toFixed(1)}%`;
            }

            if (data.sl_distance !== undefined) {
                document.getElementById('sl-distance').innerText = `+$${data.sl_distance.toFixed(2)}`;
            }

            if (data.funding_rate !== undefined) {
                document.getElementById('funding-rate').innerText = `${data.funding_rate >= 0 ? '+' : ''}${(data.funding_rate * 100).toFixed(4)}%`;
            }

            if (data.short_liq_target) {
                document.getElementById('short-liq').innerText = `$${data.short_liq_target.toLocaleString()}`;
            }

            if (data.long_liq_danger) {
                document.getElementById('long-liq').innerText = `$${data.long_liq_danger.toLocaleString()}`;
            }

            if (data.fear_and_greed) {
                document.getElementById('fng-score').innerText = data.fear_and_greed;
                document.getElementById('fng-status').innerText = data.fng_desc.toUpperCase();
            }

            if (data.eth_tvl) {
                document.getElementById('eth-tvl').innerText = `$${(data.eth_tvl / 1e9).toFixed(2)}B`;
            }

            if (data.rsi_val !== undefined) {
                document.getElementById('rsi-val').innerText = data.rsi_val.toFixed(1);
            }

            if (data.btc_filter_status !== undefined) {
                const fElem = document.getElementById('btc-filter');
                fElem.innerText = data.btc_filter_status;
                fElem.className = 'stat-val ' + (data.btc_filter_status === 'PASS' ? 'green' : 'red');
            }

            if (data.win_rate !== undefined) {
                document.getElementById('win-rate').innerText = `${data.win_rate.toFixed(1)}% (${data.total_trades} trades)`;
            }

            if (data.total_pnl !== undefined) {
                const pnlElem = document.getElementById('total-pnl');
                pnlElem.innerText = `$${data.total_pnl.toFixed(2)}`;
                pnlElem.className = 'stat-val ' + (data.total_pnl >= 0 ? 'green' : 'red');
            }

            if (data.auto_be_active !== undefined) {
                const beElem = document.getElementById('auto-be');
                beElem.innerText = data.auto_be_active ? "ACTIVE" : "Standby";
                beElem.className = 'stat-val ' + (data.auto_be_active ? 'green' : 'highlight');
            }

            if (data.current_sl !== undefined) {
                document.getElementById('current-sl-text').innerText = `$${data.current_sl.toLocaleString('en-US', { minimumFractionDigits: 2 })}`;
                
                slLine.applyOptions({
                    price: data.current_sl,
                    title: data.auto_be_active ? `BREAK-EVEN ($${data.current_sl})` : `STOP LOSS ($${data.current_sl})`,
                    color: data.auto_be_active ? '#FFD600' : '#FF1744'
                });
            }

            // Update Chart Series
            if (data.candles && data.candles.length > 0) {
                candleSeries.setData(data.candles);
                ema9Series.setData(data.ema9_series);
                ema21Series.setData(data.ema21_series);
                rsiSeries.setData(data.rsi_series);

                chart.timeScale().fitContent();
            }

        } catch (err) {
            console.error("Error updating dashboard:", err);
        }
    }

    // Initial update & 3-second polling
    updateDashboard();
    setInterval(updateDashboard, 3000);
});
