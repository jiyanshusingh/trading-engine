# Presentation Diagrams

Copy and paste these Mermaid diagrams into your presentation slides as needed.

---

## Diagram 1: System Architecture (Slide 5)

```mermaid
flowchart TD
    A["Market Data<br/>Upstox API"] --> B["Feature Engineering<br/>33-35 features per bar"]
    B --> C["ML Strategies<br/>(XGBoost - Generative AI)"]
    B --> D["Expert Strategies<br/>(Rule-based - Chain of Thought)"]
    
    C --> C1["ML Standalone<br/>35 features, thr 0.80"]
    C --> C2["ML Opening Breakout<br/>33 features, thr 0.70"]
    C --> C3["ML Filter<br/>43 features, thr 0.60"]
    
    D --> D1["RSM Swing<br/>7-factor engine"]
    D --> D2["Combined Swing<br/>7-factor + day windows"]
    D --> D3["Manual Institutional<br/>11-factor engine"]
    D --> D4["Daily Trend<br/>6-factor + Donchian"]
    
    C1 & C2 & C3 & D1 & D2 & D3 & D4 --> E["Decision Filter<br/>Confidence thresholds"]
    E --> F["Risk Manager<br/>₹50k, 1% risk/trade"]
    F --> G["Order Execution<br/>Upstox Paper Trading"]
```

---

## Diagram 2: Walk-Forward Validation (Slide 8)

```mermaid
flowchart LR
    subgraph Fold1["Fold 1"]
        T1A["Train<br/>Jul-Dec 2024<br/>120,439 rows"] --> T1B["Test<br/>Dec 2024-May 2025<br/>100 trades, 91% WR"]
    end
    
    subgraph Fold2["Fold 2"]
        T2A["Train<br/>Jul 2024-May 2025<br/>241,214 rows"] --> T2B["Test<br/>May-Sep 2025<br/>100 trades, 83% WR"]
    end
    
    subgraph Fold3["Fold 3"]
        T3A["Train<br/>Jul 2024-Sep 2025<br/>363,405 rows"] --> T3B["Test<br/>Sep 2025-Feb 2026<br/>103 trades, 85.4% WR"]
    end
    
    subgraph Fold4["Fold 4"]
        T4A["Train<br/>Jul 2024-Feb 2026<br/>488,430 rows"] --> T4B["Test<br/>Feb-Jul 2026<br/>101 trades, 84.2% WR"]
    end
    
    Fold1 --> Fold2 --> Fold3 --> Fold4
```

---

## Diagram 3: Decision Flow — ML Strategy (Slide 6)

```mermaid
flowchart LR
    A["5-min bar completes"] --> B["Compute 33 features:<br/>gap, range, volume,<br/>RSI, ATR, EMAs, etc."]
    B --> C["Score LONG proba"]
    B --> D["Score SHORT proba"]
    C --> E{"LONG ≥ 0.70?"}
    D --> F{"SHORT ≥ 0.70?"}
    E -->|Yes| G["Enter LONG<br/>SL 0.3%, TP 1.5%"]
    F -->|Yes| H["Enter SHORT<br/>SL 0.3%, TP 1.5%"]
    E -->|No| I["Skip bar"]
    F -->|No| I
```

---

## Diagram 4: Decision Flow — Expert Strategy (Slide 7)

```mermaid
flowchart TD
    A["New 15-min bar"] --> B["Check time gate"]
    B -->|Outside window| C["Skip"]
    B -->|Inside window| D["Check day-of-week"]
    D -->|Skip day| C
    D -->|Active day| E["Evaluate Factor 1<br/>Relative Strength"]
    E --> F["Evaluate Factor 2<br/>Volume Surge"]
    F --> G["Evaluate Factor 3<br/>VWAP Separation"]
    G --> H["Continue for<br/>Factors 4-7"]
    H --> I["Sum all factors"]
    I --> J{"Score ≥ 55?"}
    J -->|Yes| K["Generate LONG signal"]
    J -->|No| C
    K --> L["Apply ML Filter"]
    L -->|Pass| M["Enter position"]
    L -->|Fail| C
```

---

## Diagram 5: Generative AI Mapping (Slide 4)

```mermaid
flowchart LR
    subgraph GenAI["Generative AI"]
        A1["Text Prompt"] --> A2["LLM"]
        A2 --> A3["Generated Text Output"]
        A2 --> A4["Probability Score"]
        A5["Temperature"] --> A2
    end
    
    subgraph TradingAI["Trading AI System"]
        B1["Feature Vector<br/>(33-35 numbers)"] --> B2["XGBoost Model"]
        B2 --> B3["Trading Decision<br/>(LONG/SHORT/NONE)"]
        B2 --> B4["Confidence Score<br/>(0.0-1.0)"]
        B5["Threshold<br/>(0.70-0.80)"] --> B2
    end
    
    A1 -.->|maps to| B1
    A2 -.->|maps to| B2
    A3 -.->|maps to| B3
    A4 -.->|maps to| B4
    A5 -.->|maps to| B5
```

---

## Diagram 6: Results Summary (Slide 10)

```mermaid
bar
    title "Net PnL by Strategy (₹50k capital, ₹)"
    "Daily Trend": 1992944
    "ML Opening Brk": 198026
    "Combined Swing": 162382
    "RSM Swing": 104027
    "Manual Inst.": 68469
    "ML Standalone": 49985
```

*(This is a Mermaid bar chart. If your presentation software doesn't support it, draw a simple bar chart manually.)*
