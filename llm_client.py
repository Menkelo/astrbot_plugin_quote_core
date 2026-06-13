from astrbot.api import logger


class LLMClient:
    @staticmethod
    async def _try_get_provider_id_by_id(context, provider_id: str) -> str | None:
        if not provider_id or not isinstance(provider_id, str) or not provider_id.strip():
            return None
        provider_id = provider_id.strip()
        try:
            provider = context.get_provider_by_id(provider_id=provider_id)
            if provider:
                return provider_id
        except:
            pass
        return None

    @staticmethod
    async def get_provider_id_with_fallback(context, config_manager, provider_id_key: str, umo: str = None) -> str | None:
        try:
            strategies = []
            seen_provider_ids = set()

            if provider_id_key:
                getter_method = f"get_{provider_id_key}"
                if hasattr(config_manager, getter_method):
                    specific_provider_id = getattr(config_manager, getter_method)()
                    if specific_provider_id and specific_provider_id not in seen_provider_ids:
                        seen_provider_ids.add(specific_provider_id)
                        strategies.append(lambda pid=specific_provider_id: LLMClient._try_get_provider_id_by_id(context, pid))

            main_provider_id = config_manager.get_llm_provider_id()
            if main_provider_id and main_provider_id not in seen_provider_ids:
                strategies.append(lambda pid=main_provider_id: LLMClient._try_get_provider_id_by_id(context, pid))

            for strategy in strategies:
                provider_id = await strategy()
                if provider_id:
                    logger.info(f"[Provider 选择] {provider_id}")
                    return provider_id

            return None

        except:
            return None
