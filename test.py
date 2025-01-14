from flask import Flask, request, jsonify
from flask_cors import CORS
from google.cloud import vision
from datetime import datetime
import mysql.connector  # 이 줄 추가
from datetime import datetime  # 이 줄 추가
import os
import re

app = Flask(__name__)
CORS(app)

os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'madcamp-week3.json'
client = vision.ImageAnnotatorClient()

# MySQL 데이터베이스 설정
DB_CONFIG = {
    'host': 'fridge-rds.cjymas6uwg1h.ap-northeast-2.rds.amazonaws.com',
    'user': 'root',
    'password': 'sojeong0',
    'database': 'myfridge',
    'port' : 3306
}
def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)

def save_detections_to_db(detections, user_email, image_url=None):
    """
    탐지된 객체들을 데이터베이스에 저장
    Spring Entity 구조에 맞춰 저장
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    saved_items = []
    try:
        for detection in detections:
            # detected_items 테이블에 데이터 삽입
            query = """
            INSERT INTO detected_items 
            (item_name, detected_at, image_url, amount, unit, user_id) 
            VALUES (%s, %s, %s, %s, %s, %s)
            """
            
            current_time = datetime.now()
            
            values = (
                detection['label'],          # item_name
                current_time,                # detected_at
                image_url,                   # image_url
                float(detection['amount']),  # amount
                detection['unit'],           # unit
                user_email                   # user_id (Google email)
            )
            
            cursor.execute(query, values)
            item_id = cursor.lastrowid
            
            saved_item = {
                'id': item_id,
                'itemName': detection['label'],
                'userId': user_email,
                'detectedAt': current_time.isoformat(),
                'imageUrl': image_url,
                'amount': detection['amount'],
                'unit': detection['unit']
            }
            saved_items.append(saved_item)
        
        conn.commit()
        return saved_items
        
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()

# 카테고리 기반 정보
CATEGORY_INFO = {
    '음료': {
        'patterns': ['사이다', '콜라', '주스', '음료', '물', '커피', '에이드', '식혜', '드링크'],
        'unit': 'ml',
        'amount': 500,
        'exceptions': {
            '박스': {'unit': '개', 'amount': 1},
            '팩': {'unit': '개', 'amount': 1}
        }
    },
    '과자': {
        'patterns': ['칩', '과자', '볼', '쿠키', '비스켓', '스낵', '캔디', '초콜릿', '껌', '웨하스'],
        'unit': '개',
        'amount': 1,
        'exceptions': {
            '대용량': {'unit': 'g', 'amount': 300}
        }
    },
    '신선식품': {
        'patterns': ['버섯', '과일', '채소', '야채', '고기', '육류', '생선', '해산물'],
        'unit': 'g',
        'amount': 300,
        'exceptions': {
            '개입': {'unit': '개', 'amount': 1}
        }
    },
    '가공식품': {
        'patterns': ['김치', '반찬', '만두', '라면', '우동', '햇반', '밥', '죽', '카레'],
        'unit': 'g',
        'amount': 500,
        'exceptions': {
            '개입': {'unit': '개', 'amount': 1}
        }
    }
}

# 자주 사용되는 특정 제품 정보
SPECIFIC_PRODUCTS = {
    '칠성사이다': {'unit': 'ml', 'amount': 500},
    '스윙칩': {'unit': '개', 'amount': 1},
    '새송이버섯': {'unit': 'g', 'amount': 200},
    '홈런볼': {'unit': '개', 'amount': 1},
}

def get_product_info(product_name, text_context=""):
    # 1. 특정 제품 확인
    if product_name in SPECIFIC_PRODUCTS:
        base_info = SPECIFIC_PRODUCTS[product_name].copy()
    else:
        # 2. 카테고리 기반 정보 확인
        base_info = None
        for category, info in CATEGORY_INFO.items():
            for pattern in info['patterns']:
                if pattern in product_name:
                    # 예외 처리 확인
                    for exception_key, exception_value in info.get('exceptions', {}).items():
                        if exception_key in product_name:
                            base_info = exception_value.copy()
                            break
                    if not base_info:
                        base_info = {'unit': info['unit'], 'amount': info['amount']}
                    break
            if base_info:
                break
        
        # 카테고리도 못 찾았으면 기본값
        if not base_info:
            base_info = {'unit': '개', 'amount': 1}

    # 3. 특수 패턴 확인
    if re.search(r'대용량|점보|패밀리|빅|라지', product_name):
        base_info['amount'] *= 2

    # 4. 구체적인 수량 정보 확인
    context = text_context if text_context else product_name
    
    # 개수 표시 확인
    quantity_match = re.search(r'(\d+)\s*(개입|개들이|팩|박스)', context)
    if quantity_match:
        base_info['unit'] = '개'
        base_info['amount'] = int(quantity_match.group(1))
    
    # 용량 표시 확인
    volume_patterns = [
        {'pattern': r'(\d+)ml', 'unit': 'ml', 'multiplier': 1},
        {'pattern': r'(\d+)L', 'unit': 'ml', 'multiplier': 1000},  # L를 ml로 변환
        {'pattern': r'(\d+)g', 'unit': 'g', 'multiplier': 1},
        {'pattern': r'(\d+)kg', 'unit': 'g', 'multiplier': 1000},  # kg를 g로 변환
    ]
    
    for pattern_info in volume_patterns:
        volume_match = re.search(pattern_info['pattern'], context, re.IGNORECASE)
        if volume_match:
            amount = int(volume_match.group(1)) * pattern_info['multiplier']
            base_info['unit'] = pattern_info['unit']
            base_info['amount'] = amount
            break

    return base_info

def extract_korean_products(text):
    # 패턴을 카테고리 정보에서 동적으로 생성
    patterns = []
    for category_info in CATEGORY_INFO.values():
        patterns.extend(category_info['patterns'])
    
    # 패턴을 정규식으로 변환
    pattern_str = '|'.join(patterns)
    korean_pattern = f'([가-힣]+(?:{pattern_str}))'
    
    products = []
    matches = re.finditer(korean_pattern, text)
    for match in matches:
        products.append(match.group(1))
    
    return products

@app.route('/detect', methods=['POST'])
def detect_objects():
    print("==== Starting new detection request ====")
    
    if 'image' not in request.files:
        print("Error: No image in request")
        return jsonify({'error': 'No image provided'}), 400
    
    if 'userEmail' not in request.form:
        print("Error: No userEmail provided")
        return jsonify({'error': 'No userEmail provided'}), 400
    
    user_email = request.form['userEmail']
    file = request.files['image']
    content = file.read()
    print(f"Received image size: {len(content)} bytes")
    
    image = vision.Image(content=content)
    
    try:
        # Vision API 호출 및 탐지 로직 (기존과 동일)
        vision_response = client.annotate_image({
            'image': image,
            'features': [
                {'type_': vision.Feature.Type.OBJECT_LOCALIZATION},
                {'type_': vision.Feature.Type.LABEL_DETECTION},
                {'type_': vision.Feature.Type.TEXT_DETECTION}
            ]
        })
        
        text_response = client.text_detection(image=image)
        full_text = ""
        if text_response.text_annotations:
            full_text = text_response.text_annotations[0].description
            print("\nText Detection Results:")
            print(full_text)
        
        detections = []
        seen_labels = set()
        filtered_words = {
            'food', 'produce', 'fruit', 'vegetable', 'ingredient', 
            'tableware', 'product', 'food group', 'comfort food',
            'finger food', 'convenience food', 'fast food', 'recipe'
        }
        
        # 한글 상품명 추가
        korean_products = extract_korean_products(full_text)
        for product in korean_products:
            if product.lower() not in seen_labels:
                product_info = get_product_info(product, full_text)
                detection = {
                    'label': product,
                    'confidence': 0.9,
                    'amount': product_info['amount'],
                    'unit': product_info['unit']
                }
                detections.append(detection)
                seen_labels.add(product.lower())
        
        # 객체 인식 결과 처리
        for obj in vision_response.localized_object_annotations:
            if obj.score > 0.6 and obj.name.lower() not in filtered_words:
                label = obj.name
                if label.lower() not in seen_labels:
                    product_info = get_product_info(label, full_text)
                    detection = {
                        'label': label,
                        'confidence': float(obj.score),
                        'amount': product_info['amount'],
                        'unit': product_info['unit']
                    }
                    detections.append(detection)
                    seen_labels.add(label.lower())
        
        print(f"\nFinal detections: {detections}")
        
        # 데이터베이스에 저장하고 저장된 결과 반환
        try:
            saved_items = save_detections_to_db(
                detections=detections,
                user_email=user_email,
                image_url=None
            )
            return jsonify(saved_items)  # 저장된 아이템 정보 반환
        except Exception as db_error:
            print(f"Database error: {str(db_error)}")
            return jsonify({'error': 'Failed to save to database'}), 500
        
    except Exception as e:
        print(f"Error occurred: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)