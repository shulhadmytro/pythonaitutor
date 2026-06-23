import os
import re
import chromadb
from sentence_transformers import SentenceTransformer
from datasets import load_dataset

def load_local_documents(file_path):
    """Reads your existing documentation.txt file."""
    if not os.path.exists(file_path):
        return [], [], []
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    pattern = r"<source_(\d+)>\s*(.*?)(?=<source_|\Z)"
    matches = re.findall(pattern, content, re.DOTALL)
    documents, metadatas, ids = [], [], []
    for source_id, text in matches:
        if text.strip():
            documents.append(text.strip())
            metadatas.append({"source": "local_doc", "source_id": int(source_id)})
            ids.append(f"doc_{source_id}")
    return documents, metadatas, ids

def load_ua_codeforces(max_samples=500):
    """Loads the Ukrainian Codeforces reasoning dataset."""
    print(f"📥 Loading 'ua-codeforces-cots-open-r1'...")
    # Using streaming=True to avoid high RAM usage
    ds = load_dataset("anon-researcher-ua/ua-codeforces-cots-open-r1", split='train', streaming=True)
    
    documents, metadatas, ids = [], [], []
    for i, entry in enumerate(ds):
        if i >= max_samples: break
        
        # We combine reasoning and code to give the bot 'intelligence'
        prompt = entry.get('prompt', '')
        reasoning_and_code = entry.get('generation', '') # Contains CoT + Python code
        
        combined_text = f"Problem: {prompt}\n\nReasoning & Solution:\n{reasoning_and_code}"
        
        documents.append(combined_text)
        metadatas.append({"source": "ua_codeforces", "index": i})
        ids.append(f"ua_cf_{i}")
    return documents, metadatas, ids

def run_training():
    model = SentenceTransformer('all-MiniLM-L6-v2')
    client = chromadb.PersistentClient(path="./python_tutor_vector_db")
    collection = client.get_or_create_collection(name="python_knowledge")

    # 1. Add Local Documentation
    docs, meta, ids = load_local_documents("documentation.txt")
    if docs:
        print(f"📄 Adding {len(docs)} local theory records...")
        collection.add(embeddings=model.encode(docs).tolist(), documents=docs, metadatas=meta, ids=ids)

    # 2. Add Codeforces Dataset
    cf_docs, cf_meta, cf_ids = load_ua_codeforces(max_samples=500)
    if cf_docs:
        print(f"🧠 Adding {len(cf_docs)} competitive programming records...")
        # Encode in batches to prevent crashes
        embeddings = model.encode(cf_docs, show_progress_bar=True, batch_size=32)
        collection.add(embeddings=embeddings.tolist(), documents=cf_docs, metadatas=cf_meta, ids=cf_ids)

    print(f"✅ Training Complete! Your bot now knows Python theory and complex algorithms.")

if __name__ == "__main__":
    run_training()