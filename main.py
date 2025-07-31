import re
import httpx
import traceback
import asyncio  # 补充导入
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import astrbot.api.message_components as Comp

ITAD_API_KEY = "71f60367ef4e9ca7fed2a4b4e6aeea0972c2d85d"
ITAD_API_BASE = "https://api.isthereanydeal.com"
STEAMWEBAPI_KEY = "JB7FYS8NA25DNZIA"
STEAMWEBAPI_PRICES = "https://api.steamwebapi.com/steam/prices"

@register("steam_price", "Maoer", "查询Steam游戏价格及史低", "1.0.0", "https://github.com/xxx/xxx")
class SteamPricePlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    @filter.command("价格")
    async def price(self, event: AstrMessageEvent, url: str):
        '''查询Steam游戏价格及史低信息，格式：/价格 <steam商店链接/游戏名>'''
        # 新增：自动识别链接或游戏名
        if not url.lower().startswith("http"):
            # 1. 不是链接，认为是游戏名，先用LLM翻译为英文
            yield event.plain_result("正在为主人查找游戏，请稍等...")
            try:
                # 调用 LLM 翻译（参考 SDGen_Maoer 用法）
                prompt = f"请将以下游戏名翻译为steam页面的英文官方名称，仅输出英文名，不要输出其他内容：{url}"
                logger.info(f"[LLM][翻译游戏名] 输入prompt: {prompt}")
                llm_response = await self.context.get_using_provider().text_chat(
                    prompt=prompt,
                    contexts=[],
                    image_urls=[],
                    func_tool=None,
                    system_prompt=""
                )
                game_en_name = llm_response.completion_text.strip()
                logger.info(f"[LLM][翻译游戏名] 输出: {game_en_name}")
            except Exception as e:
                logger.error(f"LLM翻译游戏名失败: {e}")
                yield event.plain_result("游戏名翻译失败，请重试或直接输入Steam商店链接。")
                return

            # 2. 用ITAD搜索英文名
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(
                        f"{ITAD_API_BASE}/games/search/v1",
                        params={"key": ITAD_API_KEY, "title": game_en_name, "limit": 5}
                    )
                    data = resp.json()
                    logger.info(f"[ITAD][search] 返回: {data}")
                    # 修正：ITAD返回的是list而不是dict
                    if not data or not isinstance(data, list):
                        yield event.plain_result("未找到该游戏，请检查名称或输入Steam商店链接。")
                        return
                    # 优先选 type == "game" 且 title 最接近的
                    def norm(s):
                        return s.lower().replace(" ", "") if s else ""
                    norm_en = norm(game_en_name)
                    candidates = [g for g in data if g.get("type") == "game"]
                    if not candidates:
                        candidates = data
                    # 计算相似度，优先完全匹配，其次包含
                    best = None
                    for g in candidates:
                        title = g.get("title", "")
                        if norm(title) == norm_en:
                            best = g
                            break
                    if not best:
                        for g in candidates:
                            title = g.get("title", "")
                            if norm_en in norm(title) or norm(title) in norm_en:
                                best = g
                                break
                    if not best and candidates:
                        best = candidates[0]
                    if not best:
                        yield event.plain_result("未找到该游戏的Steam商店链接。")
                        return
                    game = best
                    # 优先找steam商店链接
                    steam_url = ""
                    for url_item in game.get("urls", []):
                        if "store.steampowered.com/app" in url_item:
                            steam_url = url_item
                            break
                    # 如果没有直接的 steam 链接，则用 ITAD 的 gid 查 info 拿 appid 再拼接
                    if not steam_url and game.get("id"):
                        try:
                            async with httpx.AsyncClient(timeout=10) as client2:
                                resp2 = await client2.get(
                                    f"{ITAD_API_BASE}/games/info/v2",
                                    params={"key": ITAD_API_KEY, "id": game["id"]}
                                )
                                info2 = resp2.json()
                                appid = info2.get("appid")
                                if appid:
                                    steam_url = f"https://store.steampowered.com/app/{appid}"
                        except Exception as e:
                            logger.error(f"通过ITAD gid查appid失败: {e}\n{traceback.format_exc()}")
                    if not steam_url:
                        yield event.plain_result("未找到该游戏的Steam商店链接。")
                        return
                    # 递归调用自身，走链接流程
                    async for result in self.price(event, steam_url):
                        yield result
                    return
            except Exception as e:
                logger.error(f"ITAD搜索失败: {e}\n{traceback.format_exc()}")
                yield event.plain_result("游戏搜索失败，请重试或直接输入Steam商店链接。")
                return

        # 1. 解析appid
        m = re.match(r"https?://store\.steampowered\.com/app/(\d+)", url)
        if not m:
            yield event.plain_result("请提供正确的Steam商店链接！")
            return
        appid = m.group(1)

        # 立即回复提示消息
        yield event.plain_result("为主人查询史低信息喵~稍等稍等...")

        # --- 并发请求国区Steam信息、ITAD信息、乌克兰区Steam价格 ---
        async def fetch_steam_cn():
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(
                        f"https://store.steampowered.com/api/appdetails?appids={appid}&l=schinese"
                    )
                    data = resp.json()
                    app_data = data.get(appid, {}).get("data", {})
                    steam_name = app_data.get("name")
                    header_img = app_data.get("header_image")
                    steam_image = None
                    if header_img:
                        small_img = header_img.replace("_header.jpg", "_capsule_184x69.jpg")
                        img_resp = await client.get(small_img)
                        if img_resp.status_code == 200:
                            steam_image = small_img
                        else:
                            steam_image = header_img
                    return steam_name, steam_image
            except Exception as e:
                logger.error(f"获取Steam国区游戏信息失败: {e}\n{traceback.format_exc()}")
                return None, None

        async def fetch_itad_lookup():
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(
                        f"{ITAD_API_BASE}/games/lookup/v1",
                        params={"key": ITAD_API_KEY, "appid": appid}
                    )
                    data = resp.json()
                    logger.info(f"[ITAD][lookup] 返回: {data}")
                    if not data.get("found"):
                        return None
                    return data["game"]["id"]
            except Exception as e:
                logger.error(f"获取ITAD gid失败: {e}\n{traceback.format_exc()}")
                return None

        async def fetch_ua_price():
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(
                        "https://store.steampowered.com/api/appdetails",
                        params={"appids": appid, "cc": "ua", "l": "en"}
                    )
                    data = resp.json()
                    logger.info(f"[STEAM][UA] 返回: {data}")
                    app_data = data.get(appid, {})
                    if app_data.get("success") and app_data.get("data"):
                        price_overview = app_data["data"].get("price_overview")
                        if price_overview and "final" in price_overview and "currency" in price_overview:
                            ua_price = price_overview["final"] / 100
                            ua_currency = price_overview["currency"]
                            return ua_price, ua_currency, price_overview.get("discount_percent", 0)
                    return None, None, 0
            except Exception as e:
                logger.error(f"获取乌克兰区实时价格失败: {e}\n{traceback.format_exc()}")
                return None, None, 0

        # 并发执行
        results = await asyncio.gather(
            fetch_steam_cn(),
            fetch_itad_lookup(),
            fetch_ua_price()
        )
        steam_name, steam_image = results[0]
        gid = results[1]
        ua_price, ua_currency, ua_discount_percent = results[2]

        # steam_name, steam_image = ...; gid = ...; ua_price, ua_currency, ua_discount_percent = ...
        # 兼容 yield event.plain_result
        if gid is None:
            yield event.plain_result("未找到该游戏的 isthereanydeal id \n（试一下换个名称搜索一下）。")
            return

        # ITAD游戏基本信息
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{ITAD_API_BASE}/games/info/v2",
                    params={"key": ITAD_API_KEY, "id": gid}
                )
                info = resp.json()
                logger.info(f"[ITAD][info] 返回: {info}")
                name = info.get("title", "未知游戏")
                tags = ", ".join(info.get("tags", []))
                release = info.get("releaseDate", "")
                devs = ", ".join([d["name"] for d in info.get("developers", [])]) if info.get("developers") else ""
                itad_url = info.get("urls", {}).get("game", "")
                steam_review = ""
                for r in info.get("reviews", []):
                    if r.get("source") == "Steam":
                        steam_review = f"{r.get('score', '')}%"
                        break
        except Exception as e:
            logger.error(f"获取ITAD游戏信息失败: {e}\n{traceback.format_exc()}")
            name = tags = release = devs = itad_url = steam_review = ""

        # 国区价格和史低（ITAD）
        try:
            cn_price, cn_lowest, cn_currency = await self._get_price_and_lowest(gid, "CN")
        except Exception as e:
            logger.error(f"获取ITAD价格失败: {e}\n{traceback.format_exc()}")
            cn_price = cn_lowest = cn_currency = None

        # 如果ITAD没有国区价格，则用Steam官方API补充当前国区价格
        if cn_price is None:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(
                        "https://store.steampowered.com/api/appdetails",
                        params={"appids": appid, "cc": "cn", "l": "zh"}
                    )
                    data = resp.json()
                    app_data = data.get(appid, {})
                    if app_data.get("success") and app_data.get("data"):
                        price_overview = app_data["data"].get("price_overview")
                        if price_overview and "final" in price_overview and "currency" in price_overview:
                            cn_price = price_overview["final"] / 100
                            cn_currency = price_overview["currency"]
            except Exception as e:
                logger.error(f"补充获取Steam国区实时价格失败: {e}\n{traceback.format_exc()}")

        # 获取乌克兰区实时价格（Steam官方API）
        ua_price = ua_currency = None
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://store.steampowered.com/api/appdetails",
                    params={"appids": appid, "cc": "ua", "l": "en"}
                )
                data = resp.json()
                logger.info(f"[STEAM][UA] 返回: {data}")
                app_data = data.get(appid, {})
                if app_data.get("success") and app_data.get("data"):
                    price_overview = app_data["data"].get("price_overview")
                    if price_overview and "final" in price_overview and "currency" in price_overview:
                        # Steam官方API的final单位为分
                        ua_price = price_overview["final"] / 100
                        ua_currency = price_overview["currency"]
                    else:
                        logger.error(f"乌克兰区价格结构异常: {price_overview}")
                        ua_price = ua_currency = None
                else:
                    logger.error(f"乌克兰区无价格数据: {app_data}")
                    ua_price = ua_currency = None
        except Exception as e:
            logger.error(f"获取乌克兰区实时价格失败: {e}\n{traceback.format_exc()}")
            ua_price = ua_currency = None

        # 5. 汇率（手动定义，不再请求第三方）
        uah2cny = 0.1718  # 1UAH=0.1718人民币
        usd2cny = 7.2     # 如有需要可手动调整

        # 6. 货币转换
        def to_cny(price, currency):
            if price is None or currency is None:
                return None
            if currency == "CNY":
                return price
            if currency == "UAH":
                return round(price * uah2cny, 2)
            if currency == "USD":
                return round(price * usd2cny, 2)
            return None

        # 7. 计算百分比
        def percent_drop(now, low, regular=None):
            """
            计算折扣百分比。
            - now: 当前价
            - low: 史低价
            - regular: 原价（可选，若有则用原价和史低价算史低折扣）
            """
            if now and low and now > 0:
                # 当前价相对史低
                return f"-{round((1-low/now)*100):.0f}%"
            return "未知"

        # 8. 价格差（实时国区/乌克兰区）
        price_diff = ""
        cn_cny = to_cny(cn_price, cn_currency)
        ua_cny = to_cny(ua_price, ua_currency)
        if cn_cny is not None and ua_cny is not None and ua_cny > 0:
            price_diff = f"国区比乌区贵 {((cn_cny-ua_cny)/ua_cny*100):.2f}%（国区￥{cn_cny:.2f}，乌区￥{ua_cny:.2f}） 呢！"
        else:
            price_diff = "无法获取当前价差"

        # 9. 金额格式化
        def fmt(price, currency):
            if price is None or currency is None:
                return "未知"
            symbol = "￥" if currency == "CNY" else "₴" if currency == "UAH" else "$" if currency == "USD" else currency + " "
            return f"{symbol}{price:.2f}"

        # 国区当前折扣
        cn_discount = ""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://store.steampowered.com/api/appdetails",
                    params={"appids": appid, "cc": "cn", "l": "zh"}
                )
                data = resp.json()
                app_data = data.get(appid, {})
                if app_data.get("success") and app_data.get("data"):
                    price_overview = app_data["data"].get("price_overview")
                    if price_overview and "discount_percent" in price_overview and price_overview["discount_percent"] > 0:
                        cn_discount = f"-{price_overview['discount_percent']}%"
        except Exception as e:
            logger.error(f"获取国区实时折扣失败: {e}\n{traceback.format_exc()}")

        # 乌克兰区当前折扣
        ua_discount = ""
        if ua_discount_percent and ua_discount_percent > 0:
            ua_discount = f"-{ua_discount_percent}%"
        # 乌克兰区显示人民币对比
        ua_cny = to_cny(ua_price, ua_currency)
        ua_price_str = fmt(ua_price, ua_currency)
        # 修正：只有 ua_cny 不为 None 且大于0 时才拼接人民币价格
        if ua_cny is not None and ua_cny > 0:
            ua_price_str += f" （￥{ua_cny:.2f}）"
        if ua_discount:
            ua_price_str += f"{ua_discount}"

        # 国区价格字符串
        cn_price_str = fmt(cn_price, cn_currency)
        if cn_discount:
            cn_price_str += f" {cn_discount}"

        # 价格差（严格只显示百分比，前面加提示文字）
        cn_cny = to_cny(cn_price, cn_currency)
        ua_cny = to_cny(ua_price, ua_currency)
        if cn_cny is not None and ua_cny is not None and ua_cny > 0:
            price_diff = f"国区比乌区贵 {((cn_cny-ua_cny)/ua_cny*100):.2f}% 呢！"
        else:
            price_diff = "无法获取当前价差"

        # 10. 构建精简消息链
        chain = []
        # 优先用国区中文封面（小图）
        if steam_image:
            chain.append(Comp.Image.fromURL(steam_image))
        elif image:
            chain.append(Comp.Image.fromURL(image))
        # 优先用国区中文名
        display_name = steam_name if steam_name else name

        # 获取原价（regular）用于史低折扣显示
        regular_price = None
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://store.steampowered.com/api/appdetails",
                    params={"appids": appid, "cc": "cn", "l": "zh"}
                )
                data = resp.json()
                app_data = data.get(appid, {})
                if app_data.get("success") and app_data.get("data"):
                    price_overview = app_data["data"].get("price_overview")
                    if price_overview and "initial" in price_overview:
                        regular_price = price_overview["initial"] / 100
        except Exception as e:
            logger.error(f"获取国区原价失败: {e}\n{traceback.format_exc()}")

        # 史低折扣百分比（相对于原价）
        shidi_percent = ""
        if regular_price and cn_lowest:
            shidi_percent = f"-{round((1 - cn_lowest / regular_price) * 100):.0f}%"
        else:
            shidi_percent = percent_drop(cn_price, cn_lowest)

        msg = (
            f"{display_name}\n"
            f"国区价格: {cn_price_str}\n"
            f"史低: {fmt(cn_lowest, cn_currency)} {shidi_percent}\n"
            f"\n"
            f"乌区价格: {ua_price_str}\n"
            f"\n"
            f"{price_diff}\n"
        )
        if steam_review:
            msg += f"好评率: {steam_review}\n"
        chain.append(Comp.Plain(msg))
        yield event.chain_result(chain)

    @filter.command("史低")
    async def shidi(self, event: AstrMessageEvent, url: str):
        '''查询Steam游戏价格及史低信息，格式：/史低 <steam商店链接/游戏名>'''
        # 直接复用 price 指令逻辑
        async for result in self.price(event, url):
            yield result

    async def _get_price_and_lowest(self, gid, country):
        # 用/games/prices/v3 POST获取指定区价格和史低
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{ITAD_API_BASE}/games/prices/v3",
                    params={"key": ITAD_API_KEY, "country": country, "shops": 61},  # 61=Steam
                    json=[gid]
                )
                data = resp.json()
                logger.info(f"[ITAD][prices][{country}] 返回: {data}")
                if not data or not isinstance(data, list) or not data[0].get("deals"):
                    return None, None, None
                deals = data[0]["deals"]
                # 取Steam的当前价
                price = None
                currency = None
                for d in deals:
                    if d.get("shop", {}).get("name", "").lower() == "steam":
                        price = d.get("price", {}).get("amount")
                        currency = d.get("price", {}).get("currency")
                        break
                # 取史低价
                lowest = None
                history_low = data[0].get("historyLow", {})
                for k in ["m3", "y1", "all"]:
                    if history_low.get(k) and "amount" in history_low[k]:
                        lowest = history_low[k]["amount"]
                        break
                return price, lowest, currency
        except Exception as e:
            logger.error(f"_get_price_and_lowest error: {e}\n{traceback.format_exc()}")
            return None, None, None
