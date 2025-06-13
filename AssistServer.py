from langchain_core.messages import HumanMessage, SystemMessage
from langchain_gigachat.chat_models import GigaChat
from langchain_mistralai import ChatMistralAI
from threading import Thread
from datetime import datetime

import json
import os
import socket
import time
import logging

LLM_CONFIG_FILE = "./config/llm-config.json"
PROMT_CONFIG_FILE = "./config/promt-config.json"

HOST = '0.0.0.0'
PORT = 65432

logging.basicConfig(
	level=logging.INFO,
	format='%(asctime)s - %(levelname)s - %(message)s',
	handlers=[
		logging.StreamHandler(),
		logging.FileHandler('server.log')
	]
)
logger = logging.getLogger(__name__)

def init_config():
	default_config = {
		"endpoint": "http://example.com/api",
		"api_key": "test_key_123",
		"model": "codestral",
		"scope": "GIGACHAT_API_PERS",
		"last_updated": str(datetime.now())
	}
	try:
		if not os.path.exists(LLM_CONFIG_FILE):
			with open(LLM_CONFIG_FILE, 'w') as f:
				json.dump(default_config, f, indent=4)
			logger.info(f"Создан конфигурационный файл {LLM_CONFIG_FILE}")
			logger.warn(f"Необходимо отредактировать конфигурационный файл {LLM_CONFIG_FILE}")
		else:
			logger.info(f"Используется существующий конфигурационный файл: {LLM_CONFIG_FILE}")
	except Exception as e:
		logger.error(f"Ошибка создания конфигурации: {str(e)}")
		raise

def read_config(path):
	try:
		with open(path, 'r', encoding='utf-8') as f:
			config = json.load(f)
		logger.info("Конфигурация успешно загружена")
		return config
	except Exception as e:
		logger.error(f"Ошибка чтения конфигурации: {str(e)}")
		raise

def get_llm(config): 
	if ('GigaChat-2' == config['model']):
		return GigaChat(credentials=config['api_key'],
						scope = config['scope'],
						verify_ssl_certs=False,
						model=config['model']
						)
	elif ('codestral-latest' == config['model']):
		return ChatMistralAI(endpoint=config['endpoint'],
							api_key=api_key,
							model=config['model'],
							temperature=0,
							max_retries=2
							)
		
def invoke(llm, userRequest):
	promtConfig = read_config(PROMT_CONFIG_FILE)

	existingVarsFullPromptTxt = promtConfig['existingVarsPromptTxt'] + promtConfig['existingVarsProgTxt'] if promtConfig['existingVarsProgTxt'] else ""

	messagesProg = [
		SystemMessage(content=promtConfig['systemMessageProgTxt'] + promtConfig['systemLanguageDescription'] + promtConfig['functionsListTxt'] + existingVarsFullPromptTxt),
		HumanMessage(content=promtConfig['userPromptProgTxt'])
		# HumanMessage(content=userRequest)
	]
	logger.info(f"LLM: {llm.model}")
	progRes = llm.invoke(messagesProg)
	
	messagesProg.append(progRes)

	correctionSystemMsg = SystemMessage(content=promtConfig['systemMessageCorrectionTxt'] + promtConfig['systemLanguageDescription'] + promtConfig['functionsListTxt'] + existingVarsFullPromptTxt)
	progToJsonSysMessage = [SystemMessage(content=promtConfig['ProgToJsonConvertSysTxt'] + promtConfig['functionsListTxt'])]

	logger.info(f"Пользовательский запрос: {promtConfig['userPromptProgTxt']}")
	logger.info(f"Первичный код: {progRes.content}")

	uersRequestForCorrection = "\nТекст задачи:\n" + promtConfig['userPromptProgTxt']
	for correctionPromptTxt in promtConfig['userCorrectionPromptProgArray']:
		messagesCorrection = [
			correctionSystemMsg,
			HumanMessage(correctionPromptTxt + uersRequestForCorrection + "\nРеализация задачи в коде:\n" + progRes.content)]
		time.sleep(2) # Bound llm request frequency by 2 sec
		correctionRes = llm.invoke(messagesCorrection)
		logger.info(f"Замечания к коду: {correctionRes.content}")

		if (correctionRes.content and correctionRes.content.strip()):
			messagesProg.append(HumanMessage(promtConfig['correctionProgBaseMsgTxt'] + correctionRes.content.strip()))
			time.sleep(2) # Bound llm request frequency by 2 sec
			progRes = llm.invoke(messagesProg)
			messagesProg.append(progRes)
			logger.info(f"Скорректированный код: {progRes.content}")

	progToJsonSysMessage.append(HumanMessage(content=promtConfig['progToJsonUsrPromptTxt'] + progRes.content))
	time.sleep(2) # Bound llm request frequency by 2 sec
	jsonRes = llm.invoke(progToJsonSysMessage)

	logger.info(f"Скорректированный код: {jsonRes.content}")

	return jsonRes.content;


def handle_client(connection, client_address, llm):
	logger.info(f"Новое подключение: {client_address}")
	try:
		data = connection.recv(1024)
		logger.info(f"Получен запрос: {data}")
		if data:
			logger.debug(f"Получены данные: {data.decode()[:100]}...")
			
			respose = invoke(llm, data)
			
			connection.sendall(respose.encode())
			logger.info(f"Отправлено ответов: {len(respose)} байт")
	except Exception as e:
		logger.error(f"Ошибка обработки запроса: {str(e)}")
		connection.sendall(f"Server Error: {str(e)}".encode())
	finally:
		connection.close()
		logger.info(f"Закрыто соединение с {client_address}")

def start_server():
	try:		
		server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		server.bind((HOST, PORT))
		server.listen(5)
		logger.info(f"Сервер запущен {HOST}:{PORT}")

		llm = get_llm(read_config(LLM_CONFIG_FILE))
		
		while True:
			connection, client_address = server.accept()
			client_thread = Thread(
				target=handle_client,
				args=(connection, client_address, llm),
				daemon=True
			)
			client_thread.start()
			
	except Exception as e:
		logger.critical(f"Серверная ошибка: {str(e)}")
	finally:
		server.close()

if __name__ == '__main__':
	init_config()
	start_server()