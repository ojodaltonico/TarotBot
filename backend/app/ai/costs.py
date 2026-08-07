PRICES = {("gemini", "gemini-2.5-flash"): {"input": 0.0, "output": 0.0, "cached": 0.0}}
def estimate_cost(provider, model, input_tokens, output_tokens, cached_input_tokens=None):
    price=PRICES.get((provider, model))
    return None if price is None else input_tokens/1_000_000*price["input"] + output_tokens/1_000_000*price["output"] + (cached_input_tokens or 0)/1_000_000*price["cached"]
