"""
Market Intelligence Agents.

A research team of 23 agents built around the intrinsic value calculator:

    Chief Market Intelligence Officer
      |- Market News Research Lead        research, sentiment, stock movement,
      |                                   news credibility, market impact
      |- Equity Research Lead             fundamentals, financial forensics,
      |                                   pre-earnings intelligence
      |- Head of Industry & Geopolitical  industry research, geopolitical risk
      |- Head of Market Activity &        market volume, insider activity,
      |  Ownership Research               fund holdings, short-seller research
      |- Independent Research Review      bull case, bear case,
                                          research validation

Numbers are always computed in Python. An LLM (Groq / Gemini / NVIDIA free
tiers) is used only to read text and write narrative, and every agent has a
rule-based fallback, so a run with no API keys still completes.

Entry point: runner.run_agents(). Settings: agent_settings.yaml.
"""
