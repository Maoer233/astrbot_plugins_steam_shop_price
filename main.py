import re
import httpx
import traceback
import asyncio  # 补充导入
import datetime
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import astrbot.api.message_components as Comp
from .price_convert import to_cny

ITAD_API_BASE = "https://api.isthereanydeal.com"
STEAMWEBAPI_PRICES = "https://api.steamwebapi.com/steam/prices"

@register("astrbot_plugins_steam_shop_price", "Maoer", "查询Steam游戏价格及史低", "1.0.0", "https://github.com/Maoer233/astrbot_plugins_steam_shop_price")
class SteamPricePlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.config = config or {}
        self.itad_api_key = self.config.get("ITAD_API_KEY", "")
        self.steamwebapi_key = self.config.get("STEAMWEBAPI_KEY", "")
        self.compare_region = self.config.get("STEAM_COMPARE_REGION", "UA")

    @filter.command("史低")
    async def shidi(self, event: AstrMessageEvent, url: str, last_gid=None):
        '''查询Steam游戏价格及史低信息，格式：/史低 <steam商店链接/游戏名>'''
        # 新增：自动识别链接或游戏名
        # 修复参数丢失问题，直接用 event.message_str 去除指令前缀，保留全部参数内容
        raw_msg = event.message_str
        prefix_pattern = r"^[\.／/]*(史低|价格)\s*"
        param_str = re.sub(prefix_pattern, "", raw_msg, count=1, flags=re.IGNORECASE)
        # param_str 现在包含所有参数（包括空格和数字）
        if not param_str.lower().startswith("http"):
            game_en_name = param_str
            if not re.search(r'[\u4e00-\u9fff]', game_en_name):
                logger.info(f"[史低] 检测到无中文，直接使用原始输入: {game_en_name}")
                yield event.plain_result(f"正在为主人搜索《{game_en_name}》，主人等一小会喵...")
            else:
                try:
                    prompt = f"请将以下游戏名翻译为steam页面的英文官方名称，仅输出英文名，不要输出其他内容：{param_str}"
                    llm_response = await self.context.get_using_provider().text_chat(
                        prompt=prompt,
                        contexts=[],
                        image_urls=[],
                        func_tool=None,
                        system_prompt=""
                    )
                    game_en_name = llm_response.completion_text.strip()
                    logger.info(f"[LLM][翻译游戏名] 输出: {game_en_name}")
                    yield event.plain_result(f"正在为主人搜索《{game_en_name}》，主人等一小会喵...")
                except Exception as e:
                    logger.error(f"LLM翻译游戏名失败: {e}")
                    yield event.plain_result("游戏名翻译失败，请重试或直接输入Steam商店链接。")
                    return
            # ...后续逻辑保持不变...
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    resp = await client.get(
                        f"{ITAD_API_BASE}/games/search/v1",
                        params={"key": self.itad_api_key, "title": game_en_name, "limit": 5}
                    )
                    data = resp.json()
                    logger.info(f"[ITAD][search] 成功获取候选项，共{len(data) if isinstance(data, list) else 0}个")
                    if not data or not isinstance(data, list):
                        yield event.plain_result("未找到该游戏，请检查名称或输入Steam商店链接。")
                        return
                    def norm(s):
                        return s.lower().replace(" ", "") if s else ""
                    norm_en = norm(game_en_name)
                    candidates = [g for g in data if g.get("type") == "game"]
                    if not candidates:
                        candidates = data
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
                    # 总是展示“猜你想搜”候选项（不论是否全字匹配）
                    candidate_names = [g.get("title", "未知") for g in candidates[1:6]]
                    yield event.plain_result(
                        "为主人查询史低信息喵~稍等稍等...\n"
                        + (f"猜你想搜：\n" + "\n".join(candidate_names) if candidate_names else "")
                    )
                    # 如果没有完全匹配，依然继续查第一个候选项（即 best = candidates[0]），否则流程会中断
                    if not best:
                        if candidates:
                            best = candidates[0]
                        else:
                            # 没有候选项，直接返回
                            return
                    game = best
                    steam_url = ""
                    for url_item in game.get("urls", []):
                        if "store.steampowered.com/app" in url_item:
                            steam_url = url_item
                            break
                    # 这里加超时保护，防止ITAD接口长时间无响应导致流程卡死
                    try:
                        if not steam_url and game.get("id"):
                            async with httpx.AsyncClient(timeout=20) as client2:
                                resp2 = await asyncio.wait_for(
                                    client2.get(
                                        f"{ITAD_API_BASE}/games/info/v2",
                                        params={"key": self.itad_api_key, "id": game["id"]}
                                    ),
                                    timeout=12
                                )
                                info2 = resp2.json()
                                appid = info2.get("appid")
                                if appid:
                                    steam_url = f"https://store.steampowered.com/app/{appid}"
                    except Exception as e:
                        logger.error(f"通过ITAD gid查appid失败: {e}\n{traceback.format_exc()}")
                    # 修正：查到 steam_url 后只查一次，不递归自身，避免无限循环
                    if steam_url:
                        # 直接进入链接查询流程
                        async for result in self._query_by_url(event, steam_url):
                            yield result
                        return
                    else:
                        yield event.plain_result("未找到该游戏的Steam商店链接，或链接格式异常。请尝试更换游戏名称或直接输入Steam商店链接。")
                        return
            except Exception as e:
                logger.error(f"ITAD搜索失败: {e}\n{traceback.format_exc()}")
                yield event.plain_result("游戏搜索失败，请重试或直接输入Steam商店链接。")
                return
        else:
            url = param_str
            # 直接进入链接查询流程
            async for result in self._query_by_url(event, url):
                yield result
            return

    async def _query_by_url(self, event, url):
        # 复制原有链接查询流程（appid解析及后续逻辑）
        m = re.match(r"https?://store\.steampowered\.com/app/(\d+)", url)
        if not m:
            yield event.plain_result("请提供正确的Steam商店链接！")
            return
        appid = m.group(1)
        # ...后续逻辑保持不变...
        # --- 并发请求国区Steam信息、ITAD信息、对比区Steam价格 ---
        async def fetch_steam_cn():
            try:
                async with httpx.AsyncClient(timeout=20) as client:
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
                async with httpx.AsyncClient(timeout=20) as client:
                    resp = await client.get(
                        f"{ITAD_API_BASE}/games/lookup/v1",
                        params={"key": self.itad_api_key, "appid": appid}
                    )
                    data = resp.json()
                    gid = data["game"]["id"] if data.get("found") else None
                    logger.info(f"[ITAD][lookup] 成功获取 ITAD gid: {gid}")
                    if not data.get("found"):
                        return None
                    return gid
            except Exception as e:
                logger.error(f"获取ITAD gid失败: {e}\n{traceback.format_exc()}")
                return None

        async def fetch_compare_price():
            if self.compare_region.upper() == "NONE":
                return None, None, 0
            region = self.compare_region.upper()
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    resp = await client.get(
                        "https://store.steampowered.com/api/appdetails",
                        params={"appids": appid, "cc": region.lower(), "l": "en"}
                    )
                    data = resp.json()
                    app_data = data.get(appid, {})
                    if app_data.get("success") and app_data.get("data"):
                        price_overview = app_data["data"].get("price_overview")
                        if price_overview and "final" in price_overview and "currency" in price_overview:
                            price = price_overview["final"] / 100
                            currency = price_overview["currency"]
                            logger.info(f"[STEAM][{region}] 成功获取价格: {price} {currency}")
                            return price, currency, price_overview.get("discount_percent", 0)
                    logger.info(f"[STEAM][{region}] 未获取到价格信息")
                    return None, None, 0
            except Exception as e:
                logger.error(f"获取{region}区实时价格失败: {e}\n{traceback.format_exc()}")
                return None, None, 0

        # 并发执行
        results = await asyncio.gather(
            fetch_steam_cn(),
            fetch_itad_lookup(),
            fetch_compare_price()
        )
        steam_name, steam_image = results[0]
        gid = results[1]
        compare_price, compare_currency, compare_discount_percent = results[2]

        # steam_name, steam_image = ...; gid = ...; compare_price, compare_currency, compare_discount_percent = ...
        # 兼容 yield event.plain_result
        if gid is None:
            yield event.plain_result("未找到该游戏的 isthereanydeal id \n（试一下换个名称搜索一下）。")
            return

        # ITAD游戏基本信息
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(
                    f"{ITAD_API_BASE}/games/info/v2",
                    params={"key": self.itad_api_key, "id": gid}
                )
                info = resp.json()
                logger.info(f"[ITAD][info] 成功获取游戏信息: {info.get('title', '未知游戏')}")
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
            cn_price, cn_lowest, cn_currency, regular = await self._get_price_and_lowest(gid, "CN")
        except Exception as e:
            logger.error(f"获取ITAD价格失败: {e}\n{traceback.format_exc()}")
            cn_price = cn_lowest = cn_currency = regular = None

        # 如果ITAD没有国区价格，则用Steam官方API补充当前国区价格
        if cn_price is None:
            try:
                async with httpx.AsyncClient(timeout=20) as client:
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
                        # 只补充当前价，不补充史低，史低始终以ITAD为准
            except Exception as e:
                logger.error(f"补充获取Steam国区实时价格失败: {e}\n{traceback.format_exc()}")

        # 获取乌克兰区实时价格（Steam官方API）
        ua_price = ua_currency = None
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(
                    "https://store.steampowered.com/api/appdetails",
                    params={"appids": appid, "cc": "ua", "l": "en"}
                )
                data = resp.json()
                app_data = data.get(appid, {})
                if app_data.get("success") and app_data.get("data"):
                    price_overview = app_data["data"].get("price_overview")
                    if price_overview and "final" in price_overview and "currency" in price_overview:
                        ua_price = price_overview["final"] / 100
                        ua_currency = price_overview["currency"]
                        logger.info(f"[STEAM][UA] 成功获取价格: {ua_price} {ua_currency}")
                    else:
                        logger.info(f"[STEAM][UA] 未获取到价格信息")
                        ua_price = ua_currency = None
                else:
                    logger.info(f"[STEAM][UA] 未获取到价格信息")
                    ua_price = ua_currency = None
        except Exception as e:
            logger.error(f"获取乌克兰区实时价格失败: {e}\n{traceback.format_exc()}")
            ua_price = ua_currency = None

        # 5. 汇率（手动定义，不再请求第三方）
        uah2cny = 0.1718  # 1UAH=0.1718人民币
        usd2cny = 7.2     # 如有需要可手动调整

        # 6. 货币转换
        price_diff = ""
        cn_cny = to_cny(cn_price, cn_currency)
        compare_cny = to_cny(compare_price, compare_currency)

        # 7. 修正史低折扣百分比算法，优先用原价
        def percent_drop(now, low, regular=None):
            """
            计算折扣百分比。
            - now: 当前价
            - low: 史低价
            - regular: 原价（可选，若有则用原价和史低价算史低折扣）
            """
            if regular and low and regular > 0:
                return f"-{round((1-low/regular)*100):.0f}%"
            if now and low and now > 0:
                return f"-{round((1-low/now)*100):.0f}%"
            return "未知"

        # 史低折扣百分比
        shidi_percent = percent_drop(cn_price, cn_lowest, regular)

        # 8. 价格差（国区/对比区）
        price_diff = ""
        cn_cny = to_cny(cn_price, cn_currency)
        compare_cny = to_cny(compare_price, compare_currency)
        if cn_cny is not None and compare_cny is not None and compare_cny > 0:
            diff_val = cn_cny - compare_cny
            diff_percent = ((cn_cny - compare_cny) / compare_cny * 100)
            if diff_val < 0:
                price_diff = f"国区更便宜喵！便宜{abs(diff_val):.2f}元呢！ ({diff_percent:.2f}%)"
            else:
                price_diff = f"国区更贵喵，多花{diff_val:.2f}元呢！ (+{diff_percent:.2f}%)"
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
            async with httpx.AsyncClient(timeout=20) as client:
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

        # 对比区当前折扣
        compare_discount = ""
        if compare_discount_percent and compare_discount_percent > 0:
            compare_discount = f"-{compare_discount_percent}%"
        # 对比区显示人民币对比
        compare_cny = to_cny(compare_price, compare_currency)
        compare_price_str = fmt(compare_price, compare_currency)
        # 修正：只有 compare_cny 不为 None 且大于0 时才拼接人民币价格
        if compare_cny is not None and compare_cny > 0:
            compare_price_str += f" （￥{compare_cny:.2f}）"
        if compare_discount:
            compare_price_str += f"{compare_discount}"

        # 国区价格字符串
        cn_price_str = fmt(cn_price, cn_currency)
        if cn_discount:
            cn_price_str += f" {cn_discount}"

        # 价格差（严格只显示百分比，前面加提示文字）
        if self.compare_region.upper() == "NONE":
            compare_price_str = "(未进行对比)"
            price_diff = ""
        else:
            compare_price_str = fmt(compare_price, compare_currency)
            if compare_discount_percent and compare_discount_percent > 0:
                compare_discount = f"-{compare_discount_percent}%"
                compare_price_str += f" {compare_discount}"
            compare_cny = to_cny(compare_price, compare_currency)
            if compare_cny is not None and compare_cny > 0:
                compare_price_str += f" （￥{compare_cny:.2f}）"
            if cn_cny is not None and compare_cny is not None and compare_cny > 0:
                diff_val = cn_cny - compare_cny
                diff_percent = ((cn_cny - compare_cny) / compare_cny * 100)
                if diff_val < 0:
                    price_diff = f"国区更便宜喵！便宜{abs(diff_val):.2f}元呢！ ({diff_percent:.2f}%)"
                else:
                    price_diff = f"国区更贵喵，多花{diff_val:.2f}元呢！ (+{diff_percent:.2f}%)"
            else:
                price_diff = "无法获取当前价差"

        # 构建精简消息链
        chain = []
        if steam_image:
            chain.append(Comp.Image.fromURL(steam_image))
        # 优先用国区中文名
        display_name = steam_name if steam_name else name

        # 优化输出格式：不对比时不显示“区价格: (未进行对比)”和多余换行
        if self.compare_region.upper() == "NONE":
            msg = (
                f"{display_name}\n"
                f"国区价格: {cn_price_str}\n"
                f"史低: {fmt(cn_lowest, cn_currency)} {shidi_percent}\n"
            )
        else:
            msg = (
                f"{display_name}\n"
                f"国区价格: {cn_price_str}\n"
                f"史低: {fmt(cn_lowest, cn_currency)} {shidi_percent}\n"
                f"\n"
                f"{self.compare_region}区价格: {compare_price_str}\n"
                f"\n"
                f"{price_diff}\n"
            )
        # 去除多余的游戏名（中括号内内容）
        import re as _re
        msg = _re.sub(r"\[.*?\]", "", msg)
        if steam_review:
            msg += f"好评率: {steam_review}"
        if appid:
            msg += f"\nsteam商店链接：https://store.steampowered.com/app/{appid}"
        chain.append(Comp.Plain(msg))
        yield event.chain_result(chain)

    @filter.command("搜索游戏")
    async def search_game(self, event: AstrMessageEvent, name: str):
        '''查找Steam游戏，格式：/查找游戏 <中文游戏名>，会展示多个结果的封面和原名'''
        try:
            # 1. LLM翻译
            prompt = f"请将以下游戏名翻译为steam页面的英文官方名称，仅输出英文名，不要输出其他内容：{name}"
            logger.info(f"[LLM][查找游戏] 输入prompt: {prompt}")
            llm_response = await self.context.get_using_provider().text_chat(
                prompt=prompt,
                contexts=[],
                image_urls=[],
                func_tool=None,
                system_prompt=""
            )
            game_en_name = llm_response.completion_text.strip()
            logger.info(f"[LLM][查找游戏] 输出: {game_en_name}")
            # 修改提示，带上英文名
            yield event.plain_result(f"正在为主人查找游戏《{game_en_name}》，请稍等...")
        except Exception as e:
            logger.error(f"LLM翻译游戏名失败: {e}")
            yield event.plain_result("游戏名翻译失败，请重试。")
            return

        # 2. ITAD搜索
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(
                    f"{ITAD_API_BASE}/games/search/v1",
                    params={"key": self.itad_api_key, "title": game_en_name, "limit": 8}
                )
                data = resp.json()
                logger.info(f"[ITAD][search_game] 返回: {data}")
                if not data or not isinstance(data, list):
                    yield event.plain_result("未找到相关游戏。")
                    return
                # 3. 组装消息链
                chain = []
                from PIL import Image as PILImage
                import io
                import httpx as _httpx
                for game in data[:10]:
                    title = game.get("title", "未知")
                    # 优先用 boxart 或 banner145
                    img_url = ""
                    assets = game.get("assets", {})
                    # 优先选小图（宽高不超过100）
                    if assets.get("banner145"):
                        img_url = assets["banner145"]
                    elif assets.get("boxart"):
                        img_url = assets["boxart"]
                    elif assets.get("banner300"):
                        img_url = assets["banner300"]
                    elif assets.get("banner400"):
                        img_url = assets["banner400"]
                    elif assets.get("banner600"):
                        img_url = assets["banner600"]
                    # 获取价格（需进一步查info接口）
                    price_str = ""
                    try:
                        async with httpx.AsyncClient(timeout=8) as client2:
                            resp2 = await client2.get(
                                f"{ITAD_API_BASE}/games/info/v2",
                                params={"key": self.itad_api_key, "id": game.get("id")}
                            )
                            info2 = resp2.json()
                            # 取国区价格
                            price = None
                            currency = None
                            if "prices" in info2 and isinstance(info2["prices"], dict):
                                cn_price = info2["prices"].get("CN")
                                if cn_price and "price" in cn_price:
                                    price = cn_price["price"].get("amount")
                                    currency = cn_price["price"].get("currency")
                            if price is not None and currency:
                                price_str = f"￥{price:.2f}" if currency == "CNY" else f"{currency} {price:.2f}"
                    except Exception as e:
                        logger.error(f"查找游戏价格失败: {e}")
                    # 拼装消息
                    if img_url:
                        # 下载图片并压缩到100x100以内
                        try:
                            async with _httpx.AsyncClient(timeout=8) as img_client:
                                img_resp = await img_client.get(img_url)
                                img_resp.raise_for_status()
                                img_bytes = img_resp.content
                                with io.BytesIO(img_bytes) as f:
                                    with PILImage.open(f) as pil_img:
                                        pil_img = pil_img.convert("RGB")
                                        pil_img.thumbnail((200, 200))
                                        buf = io.BytesIO()
                                        pil_img.save(buf, format="JPEG")
                                        buf.seek(0)
                                        img_b64 = buf.read()
                                        import base64
                                        img_b64_str = base64.b64encode(img_b64).decode("utf-8")
                                        chain.append(Comp.Image.fromBase64(img_b64_str))
                        except Exception as e:
                            logger.error(f"图片压缩失败: {e}")
                    chain.append(Comp.Plain(f"{title}" + (f"  {price_str}" if price_str else "")))
                if not chain:
                    yield event.plain_result("未找到相关游戏。")
                    return
                # 不再追加“或许你要找的游戏是这些？”
                yield event.chain_result(chain)
        except Exception as e:
            logger.error(f"ITAD查找游戏失败: {e}\n{traceback.format_exc()}")
            yield event.plain_result("查找游戏失败，请重试。")

    async def _get_price_and_lowest(self, gid, country):
        # 用/games/prices/v3 POST获取指定区价格和史低
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    f"{ITAD_API_BASE}/games/prices/v3",
                    params={"key": self.itad_api_key, "country": country, "shops": 61},  # 61=Steam
                    json=[gid]
                )
                data = resp.json()
                # 只输出关键信息
                logger.info(f"[ITAD][prices][{country}] 成功获取价格和史低信息")
                logger.debug(f"[ITAD][prices][{country}] historyLow调试: {data[0].get('historyLow', {})}")
                if not data or not isinstance(data, list) or not data[0].get("deals"):
                    return None, None, None, None
                deals = data[0]["deals"]
                # 取Steam的当前价和原价
                price = None
                currency = None
                regular = None
                for d in deals:
                    if d.get("shop", {}).get("name", "").lower() == "steam":
                        price = d.get("price", {}).get("amount")
                        currency = d.get("price", {}).get("currency")
                        if d.get("regular") and "amount" in d["regular"]:
                            regular = d["regular"]["amount"]
                        break
                # 取史低价
                lowest = None
                history_low = data[0].get("historyLow", {})
                for k in ["m3", "y1", "all"]:
                    if history_low.get(k) and "amount" in history_low[k]:
                        lowest = history_low[k]["amount"]
                        break
                return price, lowest, currency, regular
        except Exception as e:
            logger.error(f"_get_price_and_lowest error: {e}\n{traceback.format_exc()}")
            return None, None, None, None
