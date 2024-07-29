import json
import typing
import re
import functools
from datetime import datetime
from pkg.plugin.context import APIHost
from pkg.provider import entities as llm_entities
from pkg.provider.modelmgr import errors


def handle_errors(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except errors.RequesterError as e:
            # self.ap.logger 是类的属性，这里使用 args[0] 代表实例对象
            args[0].ap.logger.error(f"请求错误：{e}")
            raise  # 重新抛出异常
        except Exception as e:
            args[0].ap.logger.error(f"未处理的异常：{e}")
            raise

    return wrapper


class Generator:
    def __init__(self, host: APIHost):
        self.host = host
        self.ap = host.ap
        self._jail_break = ""
        self._jail_break_type = ""
        self._speakers = []

    def _get_question_prompts(self, user_prompt: str, output_format: str = "JSON list", system_prompt: str = None) -> typing.List[llm_entities.Message]:
        messages = []
        if self._jail_break and self._jail_break_type == "before":
            messages.append(llm_entities.Message(role="system", content=self._jail_break))
        if system_prompt:
            messages.append(llm_entities.Message(role="system", content=system_prompt))
        if self._jail_break and self._jail_break_type == "after":
            messages.append(llm_entities.Message(role="system", content=self._jail_break))

        task = {
            "task": user_prompt,
            "output_format": output_format,
        }

        task_json = json.dumps(task, ensure_ascii=False)
        messages.append(llm_entities.Message(role="user", content=task_json.strip()))
        return self._save_token(messages)

    def _get_chat_prompts(self, user_prompt: str | list[llm_entities.ContentElement], system_prompt: str = None) -> typing.List[llm_entities.Message]:
        messages = []
        if self._jail_break and self._jail_break_type == "before":
            messages.append(llm_entities.Message(role="system", content=self._jail_break))
        if system_prompt:
            messages.append(llm_entities.Message(role="system", content=system_prompt))
        if self._jail_break and self._jail_break_type == "after":
            messages.append(llm_entities.Message(role="system", content=self._jail_break))
        if isinstance(user_prompt, list):
            messages.extend(user_prompt)
        else:
            messages.append(llm_entities.Message(role="user", content=user_prompt))

        return self._save_token(messages)

    def _get_image_prompts(self, content_list: list[llm_entities.ContentElement], system_prompt: str = None) -> typing.List[llm_entities.Message]:
        messages = []
        if system_prompt:
            messages.append(llm_entities.Message(role="system", content=system_prompt))
        messages.append(llm_entities.Message(role="user", content=content_list))
        return self._save_token(messages)

    @handle_errors
    async def select_from_list(self, question: str, options: list, system_prompt: str = None) -> str:
        model_info = await self.ap.model_mgr.get_model_by_name(self.ap.provider_cfg.data["model"])
        prompt = f"""Please select the most suitable option from the given list based on the question. Question: {question} List: {options}. Ensure your answer contains only one option from the list and no additional explanation or context."""
        messages = self._get_question_prompts(prompt, output_format="text", system_prompt=system_prompt)

        self.ap.logger.info("发送请求：\n{}".format(self.messages_to_readable_str(messages)))

        response = await model_info.requester.call(model=model_info, messages=messages)
        cleaned_response = self.clean_response(response.content)

        self.ap.logger.info("模型回复：\n{}".format(cleaned_response))
        return cleaned_response

    @handle_errors
    async def return_list(self, question: str, system_prompt: str = None, generate_tags: bool = False) -> list:
        model_info = await self.ap.model_mgr.get_model_by_name(self.ap.provider_cfg.data["model"])
        prompt = f"""Please design a list of types based on the question and return the answer in JSON list format. Question: {question} Ensure your answer is strictly in JSON list format, for example: ["Type1", "Type2", ...]."""
        messages = self._get_question_prompts(prompt, output_format="JSON list", system_prompt=system_prompt)

        self.ap.logger.info("发送请求：\n{}".format(self.messages_to_readable_str(messages)))

        response = await model_info.requester.call(model=model_info, messages=messages)
        cleaned_response = self.clean_response(response.content)

        self.ap.logger.info("模型回复：\n{}".format(cleaned_response))
        return self._parse_json_list(cleaned_response, generate_tags)

    @handle_errors
    async def return_json(self, question: str, system_prompt: str = None, generate_tags: bool = False) -> list:
        model_info = await self.ap.model_mgr.get_model_by_name(self.ap.provider_cfg.data["model"])
        messages = self._get_question_prompts(question, output_format="JSON", system_prompt=system_prompt)

        self.ap.logger.info("发送请求：\n{}".format(self.messages_to_readable_str(messages)))

        response = await model_info.requester.call(model=model_info, messages=messages)
        cleaned_response = self.clean_response(response.content)

        self.ap.logger.info("模型回复：\n{}".format(cleaned_response))
        return cleaned_response

    @handle_errors
    async def return_number(self, question: str, system_prompt: str = None) -> int:
        model_info = await self.ap.model_mgr.get_model_by_name(self.ap.provider_cfg.data["model"])
        prompt = f"""Please determine the numeric answer based on the question and return the answer as a number. Ensure your answer is a single number with no additional explanation or context. Question: {question}"""
        messages = self._get_question_prompts(prompt, output_format="number", system_prompt=system_prompt)

        self.ap.logger.info("发送请求：\n{}".format(self.messages_to_readable_str(messages)))

        response = await model_info.requester.call(model=model_info, messages=messages)
        cleaned_response = self.clean_response(response.content)

        self.ap.logger.info("模型回复：\n{}".format(cleaned_response))
        return self._parse_number(cleaned_response)

    @handle_errors
    async def return_string(self, question: str, system_prompt: str = None) -> str:
        model_info = await self.ap.model_mgr.get_model_by_name(self.ap.provider_cfg.data["model"])
        messages = self._get_question_prompts(question, output_format="text", system_prompt=system_prompt)

        self.ap.logger.info("发送请求：\n{}".format(self.messages_to_readable_str(messages)))

        response = await model_info.requester.call(model=model_info, messages=messages)
        cleaned_response = self.clean_response(response.content)

        self.ap.logger.info("模型回复：\n{}".format(cleaned_response))
        return cleaned_response

    @handle_errors
    async def return_image(self, content_list: list[llm_entities.ContentElement], system_prompt: str = None) -> str:
        model_info = await self.ap.model_mgr.get_model_by_name(self.ap.provider_cfg.data["model"])
        messages = self._get_image_prompts(content_list, system_prompt)

        self.ap.logger.info("发送请求：\n{}".format(self.messages_to_readable_str(messages)))

        response = await model_info.requester.call(model=model_info, messages=messages)
        cleaned_response = self.clean_response(response.content)

        self.ap.logger.info("模型回复：\n{}".format(cleaned_response))
        return cleaned_response

    @handle_errors
    async def return_chat(self, request: str | list[llm_entities.ContentElement], system_prompt: str = None) -> str:
        model_info = await self.ap.model_mgr.get_model_by_name(self.ap.provider_cfg.data["model"])
        messages = self._get_chat_prompts(request, system_prompt)

        self.ap.logger.info("发送请求：\n{}".format(self.messages_to_readable_str(messages)))

        response = await model_info.requester.call(model=model_info, messages=messages)
        cleaned_response = self.clean_response(response.content)

        self.ap.logger.info("模型回复：\n{}".format(cleaned_response))
        return cleaned_response

    def clean_response(self, response: str) -> str:
        if self._speakers:
            # 使用正则去掉self._speakers中的任何名称，后跟冒号或中文冒号及其后的空格
            speakers_pattern = "|".join([re.escape(speaker) for speaker in self._speakers])
            pattern = rf"^(?:{speakers_pattern})[:：]\s*"
            cleaned_response = re.sub(pattern, "", response)
        else:
            cleaned_response = response
        cleaned_response = self._remove_surrounding_quotes(cleaned_response)
        # 删除特定破甲字符串
        cleaned_response = cleaned_response.replace("<结束无效提示>", "")

        return cleaned_response

    def _remove_surrounding_quotes(self, text: str) -> str:
        # 定义匹配中英文单双引号的正则表达式
        pattern = r"^([\"“‘'])?(.*?)([\"”’'])?$"
        # 检查字符串是否仅头尾有引号
        match = re.match(pattern, text)
        if match:
            start_quote, content, end_quote = match.groups()
            if start_quote and end_quote:
                # 确保头尾引号匹配，并且中间内容不包含未配对的头尾引号
                if start_quote in ('"', "“", "‘") and end_quote in ('"', "”", "’") and content.count(start_quote) == content.count(end_quote):
                    return content
                elif start_quote in ("'", "‘", "’") and end_quote in ("'", "’", "‘") and content.count(start_quote) == content.count(end_quote):
                    return content
            elif start_quote:
                # 如果只有起始引号而没有结束引号
                if content.count(start_quote) == 0:
                    return content
            elif end_quote:
                # 如果只有结束引号而没有起始引号
                if content.count(end_quote) == 0:
                    return content
        return text

    def _parse_json_list(self, response: str, generate_tags: bool = False) -> list:
        try:
            # Fix unbalanced square brackets and quotes in the whole response
            if not self._is_balanced(response, "[", "]"):
                response += "]"

            start_index = response.find("[")
            end_index = response.rfind("]") + 1

            if start_index == -1 or end_index == 0:
                self.ap.logger.info("No valid JSON array found in the response")
                return []

            # Extract the JSON part of the response
            json_str = response[start_index:end_index]

            json_str = re.sub(r",\s*(?=])", "", json_str)  # Remove trailing commas before closing bracket
            json_str = re.sub(r"[^\u4e00-\u9fa5A-Za-z\s\[\],\":]", " ", json_str).strip()  # Remove invalid characters and strip

            parsed_list = json.loads(json_str)

            if isinstance(parsed_list, list):
                if generate_tags:
                    # In terms of tag generation, the tested deepseek behaves abnormally unstable, and other models may also be unstable. Splitting into single words is a compromise.
                    unique_tags = {word.strip() for tag in parsed_list for word in tag.split() if word.strip()}
                    return list(unique_tags)
                else:
                    return parsed_list
            else:
                self.ap.logger.info("Parsed JSON is not a list: {}".format(parsed_list))
                return []
        except json.JSONDecodeError as e:
            self.ap.logger.info(f"JSON Decode Error: {e} | Response: {response}")
            return []

    def _parse_number(self, response: str) -> int:
        try:
            return int(response)
        except ValueError:
            self.ap.logger.info("Value Error: {}".format(response))
            return 0

    def _is_balanced(self, string: str, open_char: str, close_char: str) -> bool:
        return string.count(open_char) == string.count(close_char)

    def _save_token(self, messages: typing.List[llm_entities.Message]) -> typing.List[llm_entities.Message]:
        punctuation_map = {"，": ",", "。": ".", "“": '"', "”": '"', "？": "?", "！": "!", "《": "<", "》": ">", "、": ","}

        def replace_punctuation(text: str) -> str:
            for cn, en in punctuation_map.items():
                text = text.replace(cn, en)
            return text

        new_messages = []

        for message in messages:
            if isinstance(message.content, list):
                new_content = []
                for elem in message.content:
                    if elem.type == "text" and elem.text:
                        new_text = replace_punctuation(elem.text)
                        new_elem = llm_entities.ContentElement.from_text(new_text)
                    else:
                        new_elem = elem
                    new_content.append(new_elem)
                new_message = llm_entities.Message(role=message.role, content=new_content)
                new_messages.append(new_message)
            else:
                new_message = llm_entities.Message(role=message.role, content=replace_punctuation(message.content))
                new_messages.append(new_message)

        return new_messages

    def messages_to_readable_str(self, messages: typing.List[llm_entities.Message]) -> str:
        return "\n".join(message.readable_str() for message in messages)

    def get_chinese_current_time(self):
        current_time = datetime.now()
        chinese_time = current_time.strftime("%y年%m月%d日%H时%M分")
        return chinese_time

    def set_jail_break(self, jail_break: str, type: str):
        self._jail_break = jail_break
        self._jail_break_type = type

    def set_speakers(self, speakers: list):
        self._speakers = speakers
