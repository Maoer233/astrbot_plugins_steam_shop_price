# 价格转换工具
# 支持自定义维护汇率，直接修改 rates 字典即可
# 用法: from .price_convert import to_cny
#       cny_price = to_cny(price, currency)

rates = {
    "CNY": 1.0,      # 人民币
    "UAH": 0.17,   # 乌克兰格里夫纳
    "USD": 7.11,      # 美元
    "JPY": 0.05,    # 日元
    "KRW": 0.0053,   # 韩元
    "EUR": 8.38,      # 欧元
    "RUB": 0.085,    # 俄罗斯卢布
    "TR": 0.17,     # 土耳其里拉
}

def to_cny(price, currency, custom_rates=None):
    """
    将指定货币价格转换为人民币。
    price: 金额
    currency: 货币代码（如 CNY, USD, UAH, JPY, KRW, EUR, RUB）
    custom_rates: 可选，用户自定义汇率字典
    """
    if price is None or currency is None:
        return None
    r = custom_rates if custom_rates else rates
    rate = r.get(currency.upper())
    if rate:
        return round(price * rate, 2)
    return None
