# def start_worker():
#     import asyncio
#     from google.cloud import pubsub_v1
#     from app.services.classification_service import NLPService
#     from app.config.env_config import env
#     from app.repositories.journal_repository import get_journal_by_id, update_journal_wellness_state
#     from app.utils.crypto_utils import decrypt
#     import json
#
#     PROJECT_ID = "heron-wellnest"
#     SUBSCRIPTION_ID = "journal-topic-sub"
#
#     id_to_label = {
#         0: "L1", # Anxiety
#         1: "L2", # Normal
#         1: "L2", # Normal
#         2: "L3", # Depression
#         3: "L4", # Suicidal
#         4: "L5" # Stress
#     }
#
#     nlp_service = NLPService(model_path=env.MODEL_PATH, id_to_label=id_to_label)
#     subscriber = pubsub_v1.SubscriberClient()
#     subscription_path = subscriber.subscription_path(PROJECT_ID, SUBSCRIPTION_ID)
#
#     # ✅ Create a loop and run it in the current thread
#     loop = asyncio.new_event_loop()
#     asyncio.set_event_loop(loop)
#
#     async def handle_message(payload):
#         print(f"🔍 Handling journal for user: {payload}")
#         event_type = payload.get("eventType", "")
#         user_id = payload.get("userId", "")
#         journal_id = payload.get("journalId", "")
#
#         print(f"🔍 Handling journal {journal_id} for user {user_id}")
#
#         if event_type != "JOURNAL_ENTRY_CREATED":
#             print(f"Ignoring event type: {event_type}")
#             return
#
#         print("retrieving journal entry...")
#         encrypted_content = await get_journal_by_id(journal_id, user_id)
#         print(f"🔐 Fetched encrypted content: {encrypted_content}")
#
#         if not encrypted_content:
#             print(f"⚠️ No journal entry found for journal_id={journal_id}, user_id={user_id}")
#             return
#
#         decrypted_content = decrypt(
#             encrypted=encrypted_content,
#             secret=env.CONTENT_ENCRYPTION_KEY
#         )
#         print(f"🧩 Decrypted: {decrypted_content[:80]}...")
#
#         preds = nlp_service.analyze_text(decrypted_content)
#         print(f"🎯 Prediction: {preds}")
#
#         await update_journal_wellness_state(journal_id, user_id, preds)
#         print(f"✅ Updated wellness state for journal {journal_id}")
#
#     def callback(message):
#         try:
#             data = message.data.decode("utf-8")
#             payload = json.loads(data)
#             print(f"📩 Received: {payload}")
#
#             # ✅ Schedule coroutine safely into the loop
#             asyncio.run_coroutine_threadsafe(handle_message(payload), loop)
#             message.ack()
#
#         except Exception as e:
#             print(f"Worker error: {e}")
#             message.nack()
#
#     print(f"🚀 Listening on {subscription_path}")
#
#     # ✅ Run Pub/Sub in another thread, while loop runs in main thread
#     from threading import Thread
#     def run_subscriber():
#         streaming_pull_future = subscriber.subscribe(subscription_path, callback=callback)
#         with subscriber:
#             try:
#                 streaming_pull_future.result()
#             except Exception as e:
#                 print(f"Worker error: {e}")
#                 streaming_pull_future.cancel()
#
#     Thread(target=run_subscriber, daemon=True).start()
#
#     # ✅ Keep the asyncio loop running forever
#     try:
#         loop.run_forever()
#     except KeyboardInterrupt:
#         print("🛑 Shutting down worker...")
#     finally:
#         loop.stop()
