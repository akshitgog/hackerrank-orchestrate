def process_user_risk(user_history: dict) -> list[str]:
    """
    Ingests the full user history object, parses pre-existing flags, 
    and actively calculates new risk signals based on claim statistics.
    Returns a deduplicated list of risk flags.
    """
    flags = set()
    
    # 1. Parse existing history flags from the string (guaranteed flat by data_loader)
    history_flags_str = user_history.get("history_flags", "")
    if history_flags_str and str(history_flags_str).lower().strip() != "none":
        parsed = [flag.strip() for flag in str(history_flags_str).split(";") if flag.strip()]
        flags.update(parsed)
            
    # 2. Compute dynamic risk from numerical statistics
    try:
        rejected = int(user_history.get("rejected_claim", 0))
        recent = int(user_history.get("last_90_days_claim_count", 0))
        
        # Rule A: High recent claim velocity (>= 3 claims in 90 days)
        if recent >= 3:
            flags.add("user_history_risk")
            
        # Rule B: High rejection rate (>= 2 previously rejected claims)
        if rejected >= 2:
            flags.add("user_history_risk")
            
    except (ValueError, TypeError):
        # Fallback safely if CSV data is dirty or missing fields
        pass
        
    return sorted(list(flags))
