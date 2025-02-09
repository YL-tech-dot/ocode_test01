import logging
import os
import cv2
import dlib
import torch
import torch.nn as nn
import numpy as np
import pickle
import face_recognition
from PIL import Image, ImageDraw, ImageFont
from torchvision import models, transforms
from ultralytics import YOLO
from mtcnn import MTCNN
import piexif
from abc import ABC, abstractmethod
import io
import shutil
from pathlib import Path
import warnings
#
# =========================
# 로깅 및 경고 설정
# =========================
def setup_warnings_and_logging():
    """경고 및 로깅 설정

    경고 메시지를 무시하고, 로그 출력을 INFO 레벨로 설정한다.
    """
    warnings.filterwarnings("ignore", category=UserWarning)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    #
#
# =========================
# 이미지 처리 함수들
# =========================
def resize_image_with_padding(image, target_size):
    """이미지를 리사이즈하고 패딩을 추가하는 함수

    주어진 크기에 맞게 이미지를 리사이즈하고, 남은 공간을 패딩으로 채운다.
    
    Args:
        image: 원본 이미지 배열
        target_size: 목표 이미지 크기

    Returns:
        new_img: 패딩이 추가된 리사이즈된 이미지
        scale: 이미지의 스케일 비율
        top: 위쪽 패딩 크기
        left: 왼쪽 패딩 크기
    """
    h, w, _ = image.shape
    scale = target_size / max(h, w)
    resized_img = cv2.resize(image, (int(w * scale), int(h * scale)))
    #
    delta_w = target_size - resized_img.shape[1]
    delta_h = target_size - resized_img.shape[0]
    top, bottom = delta_h // 2, delta_h - (delta_h // 2)
    left, right = delta_w // 2, delta_w - (delta_w // 2)
    #
    color = [0, 0, 0]  # 패딩 색상은 검정색
    new_img = cv2.copyMakeBorder(resized_img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)
    #
    return new_img, scale, top, left
    #
#
def draw_korean_text(config, image, text, position, font_size, font_color=(255, 255, 255), background_color=(0, 0, 0)):
    """이미지에 한글 텍스트를 그리는 함수

    주어진 위치에 한글 텍스트를 이미지에 그린다.
    
    Args:
        config: 폰트 경로를 포함하는 설정 객체
        image: 원본 이미지 배열
        text: 그릴 텍스트
        position: 텍스트를 그릴 위치 (x, y)
        font_size: 텍스트 크기
        font_color: 텍스트 색상 (기본값: 흰색)
        background_color: 텍스트 배경 색상 (기본값: 검정색)

    Returns:
        텍스트가 추가된 이미지 배열
    """
    font_path = config['font_path']
    #
    if not text:  # 텍스트가 비어있으면 이미지 그대로 반환
        return image
        #
    #
    font = ImageFont.truetype(font_path, int(font_size))
    img_pil = Image.fromarray(image)
    draw = ImageDraw.Draw(img_pil)
    #
    # 텍스트 크기 측정
    text_bbox = draw.textbbox((0, 0), text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    #
    # 텍스트에 맞춰 박스 크기 조정
    box_x0 = position[0] - 5
    box_y0 = position[1] - 5
    box_x1 = position[0] + text_width + 5
    box_y1 = position[1] + text_height + 5
    #
    # 이미지가 텍스트를 수용할 수 있도록 크기를 확장
    if box_x1 > image.shape[1] or box_y1 > image.shape[0]:
        new_width = max(box_x1, image.shape[1])
        new_height = max(box_y1, image.shape[0])
        extended_img = np.ones((new_height, new_width, 3), dtype=np.uint8) * 0  # 흰색 배경
        extended_img[:image.shape[0], :image.shape[1]] = image
        img_pil = Image.fromarray(extended_img)
        draw = ImageDraw.Draw(img_pil)
        #
    #
    # 배경 박스 그리기
    draw.rectangle([box_x0, box_y0, box_x1, box_y1], fill=background_color)
    #
    # 텍스트 그리기
    draw.text(position, text, font=font, fill=font_color)
    #
    return np.array(img_pil)
    #
#
def extend_image_with_text(config, image, text, font_size, font_color=(255, 255, 255), background_color=(0, 0, 0)):
    """이미지를 확장하고 텍스트를 추가하는 함수

    이미지 위쪽에 텍스트가 들어갈 공간을 추가하고, 텍스트를 그린다.
    
    Args:
        config: 폰트 경로를 포함하는 설정 객체
        image: 원본 이미지 배열
        text: 그릴 텍스트
        font_size: 텍스트 크기
        font_color: 텍스트 색상 (기본값: 흰색)
        background_color: 텍스트 배경 색상 (기본값: 검정색)

    Returns:
        텍스트가 추가된 확장된 이미지 배열
    """
    font_path = config['font_path']
    height, width, _ = image.shape
    #
    # 텍스트 크기 계산
    font = ImageFont.truetype(font_path, font_size)
    line_spacing = int(font_size * 1.5)
    text_lines = text.count('\n') + 1
    total_text_height = line_spacing * text_lines
    #
    # 새 이미지 생성 (텍스트를 위한 공간 + 원본 이미지)
    extended_image = np.zeros((height + total_text_height + 20, width, 3), dtype=np.uint8)  # 검정색 배경
    extended_image[total_text_height + 20:, 0:width] = image
    #
    # 텍스트 추가
    extended_image_pil = Image.fromarray(extended_image)
    draw = ImageDraw.Draw(extended_image_pil)
    draw.rectangle([(0, 0), (width, total_text_height + 20)], fill=background_color)
    draw.text((10, 10), text, font=font, fill=font_color)
    #
    return np.array(extended_image_pil)
    #
#
def copy_image_and_add_metadata(image_path, output_folder):
    """이미지를 복사하고 메타데이터를 추가하는 함수

    이미지 파일을 복사한 후 Exif 메타데이터를 추가한다.
    
    Args:
        image_path: 원본 이미지 경로
        output_folder: 복사된 이미지가 저장될 폴더 경로
    """
    os.makedirs(output_folder, exist_ok=True)
    # output_folder 경로에 이미지 복사
    shutil.copy(image_path, output_folder)
    # 복사된 이미지 경로
    copied_image_path = os.path.join(output_folder, os.path.basename(image_path))
    #
    # 복사된 이미지 연 후 메타데이터 추가
    with Image.open(copied_image_path) as meta_im:
        if meta_im.mode == 'RGBA':
            meta_im = meta_im.convert('RGB')
            #
        #
        thumb_im = meta_im.copy()
        o = io.BytesIO()
        thumb_im.thumbnail((50, 50), Image.Resampling.LANCZOS)
        thumb_im.save(o, "jpeg")
        thumbnail = o.getvalue()
        #
        zeroth_ifd = {
            piexif.ImageIFD.Make: u"oldcamera",
            piexif.ImageIFD.XResolution: (96, 1),
            piexif.ImageIFD.YResolution: (96, 1),
            piexif.ImageIFD.Software: u"piexif",
            piexif.ImageIFD.Artist: u"0!code",
        }

        exif_ifd = {
            piexif.ExifIFD.DateTimeOriginal: u"2099:09:29 10:10:10",
            piexif.ExifIFD.LensMake: u"LensMake",
            piexif.ExifIFD.Sharpness: 65535,
            piexif.ExifIFD.LensSpecification: ((1, 1), (1, 1), (1, 1), (1, 1)),
        }

        gps_ifd = {
            piexif.GPSIFD.GPSVersionID: (2, 0, 0, 0),
            piexif.GPSIFD.GPSAltitudeRef: 1,
            piexif.GPSIFD.GPSDateStamp: u"1999:99:99 99:99:99",
        }

        first_ifd = {
            piexif.ImageIFD.Make: u"oldcamera",
            piexif.ImageIFD.XResolution: (40, 1),
            piexif.ImageIFD.YResolution: (40, 1),
            piexif.ImageIFD.Software: u"piexif"
        }

        exif_dict = {"0th": zeroth_ifd, "Exif": exif_ifd, "GPS": gps_ifd, "1st": first_ifd, "thumbnail": thumbnail}
        exif_bytes = piexif.dump(exif_dict)

        meta_im.save(copied_image_path, exif=exif_bytes)
        logging.info(f"이미지가 저장되었습니다. {copied_image_path}")

def print_image_exif_data(image_path):
    """이미지의 Exif 데이터를 출력하는 함수

    이미지 파일에서 Exif 데이터를 읽고 출력한다.
    
    Args:
        image_path: 이미지 파일 경로
    """
    with Image.open(image_path) as im:
        exif_data = piexif.load(im.info['exif'])
        print(exif_data)

def draw_face_boxes(image, faces, color=(0, 255, 0), thickness=2):
    """얼굴 주위에 바운딩박스를 그리는 함수

    얼굴 좌표를 기반으로 이미지를 사각형으로 표시한다.
    
    Args:
        image: 원본 이미지 배열
        faces: 얼굴 좌표 리스트
        color: 바운딩 박스 색상 (기본값: 녹색)
        thickness: 바운딩 박스 두께 (기본값: 2)

    Returns:
        얼굴 바운딩 박스가 추가된 이미지 배열
    """
    for (x, y, w, h) in faces:
        cv2.rectangle(image, (x, y), (w, h), color, thickness)

# =========================
# 추상화: AI Model 인터페이스
# =========================
class AIModel(ABC):
    @abstractmethod
    def __init__(self, model_path):
        """
        모델을 로드하는 메서드
        
        모델을 불러오는 중 예외가 발생할 수 있으므로 try-except 구문을 사용하여
        모델 로드 중 발생하는 예외를 처리하고 로깅한다. 
        
        로드에 실패한 경우 None을 반환하도록 구현.
        
        구체적 구현은 하위 클래스에서 제공.
        
        추상 메서드로 설정하여 하위 클래스에서 강제적으로 구현되도록 함.
        """
        pass
        #
    #
    @abstractmethod
    def predict(self, image, image_path=None):
        """
        이미지 또는 이미지 경로를 입력받아 얼굴 좌표를 예측하는 메서드.
        
        각 모델마다 반환하는 얼굴 좌표의 형식이 다르므로, 추상화를 통해 통일된 형식으로 반환하도록 구현.
        
        구체적 구현은 하위 클래스에서 제공.
        """
        pass
        #
    #
#
# =========================
# Dlib 모델 Face Detector 구현
# =========================
class DlibFaceDetector(AIModel):
    def __init__(self, model_path):
        """Dlib 얼굴 탐지 모델 로드"""
        try:
            logging.info(f"Dlib 모델 로드 중: {model_path}")
            self.detector = dlib.cnn_face_detection_model_v1(model_path)
        except FileNotFoundError:
            logging.error(f"Dlib 모델 파일을 찾을 수 없습니다: {model_path}")
            self.detector = None
        except Exception as e:
            logging.error(f"Dlib 모델 로드 중 오류 발생: {e}")
            self.detector = None
            #
        #
    #
    def predict(self, image):
        """Dlib을 이용해 이미지에서 얼굴을 탐지"""
        if self.detector is None:
            logging.error("Dlib 모델이 로드되지 않았습니다.")
            return []
        
        # Dlib 얼굴 탐지기 실행, 얼굴 좌표 반환
        return [(d.rect.left(), d.rect.top(), d.rect.right(), d.rect.bottom()) for d in self.detector(image, 1)]
        #
    #
#
# =========================
# YOLO 모델 Face Detector 구현
# =========================
class YOLOFaceDetector(AIModel):
    def __init__(self, model_path):
        """YOLO 얼굴 탐지 모델 로드"""
        try:
            logging.info(f"YOLO 모델 로드 중: {model_path}")
            self.detector = YOLO(model_path)
        except FileNotFoundError:
            logging.error(f"YOLO 모델 파일을 찾을 수 없습니다: {model_path}")
            self.detector = None
        except Exception as e:
            logging.error(f"YOLO 모델 로드 중 오류 발생: {e}")
            self.detector = None
            #
        #
    #
    def predict(self, image_path):
        """YOLO을 이용해 이미지에서 얼굴을 탐지"""
        if self.detector is None:
            logging.error("YOLO 모델이 로드되지 않았습니다.")
            return []
        
        # YOLO 모델을 통해 얼굴 탐지, 좌표 반환
        results = self.detector.predict(image_path, conf=0.35, imgsz=1280, max_det=1000)
        return [(int(box.xyxy[0][0]), int(box.xyxy[0][1]), int(box.xyxy[0][2]), int(box.xyxy[0][3])) for result in results for box in result.boxes]
        #
    #
#
# =========================
# MTCNN 모델 Face Detector 구현
# =========================
class MTCNNFaceDetector(AIModel):
    def __init__(self):
        """MTCNN 얼굴 탐지 모델 로드"""
        try:
            logging.info(f"MTCNN 모델 로드 중...")
            self.detector = MTCNN()
        except FileNotFoundError:
            logging.error(f"MTCNN 모델 파일을 찾을 수 없습니다!")
            self.detector = None
        except Exception as e:
            logging.error(f"MTCNN 모델 로드 중 오류 발생: {e}")
            self.detector = None
            #
        #
    #
    def predict(self, image):
        """MTCNN을 이용해 이미지에서 얼굴을 탐지"""
        if self.detector is None:
            logging.error("MTCNN 모델이 로드되지 않았습니다.")
            return []
        
        # MTCNN 모델을 통해 얼굴 탐지, 좌표 반환
        return [(f['box'][0], f['box'][1], f['box'][0] + f['box'][2], f['box'][1] + f['box'][3]) for f in self.detector.detect_faces(image)]
        #
    #
#
# =========================
# FairFace 모델 Face Predictor 구현
# =========================
class FairFacePredictor(AIModel):
    def __init__(self, model_path):
        """FairFace 모델 로드"""
        try:
            # GPU가 있다면 GPU를 사용하고, 그렇지 않으면 CPU를 사용
            self.device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
            logging.info(f"FairFace 모델 load 중: {model_path}")
            
            # ResNet34 모델을 로드하여 마지막 레이어를 수정 (18개 클래스)
            model = models.resnet34(pretrained=True)
            model.fc = nn.Linear(model.fc.in_features, 18)
            model.load_state_dict(torch.load(model_path, map_location=self.device))
            self.model = model.to(self.device).eval()
            
            logging.info("FairFace 모델 load 완료")
        except Exception as e:
            logging.error(f"FairFace 모델 로드 중 오류 발생: {e}")
            self.model = None
            #
        #
    #
    def predict(self, face_image):
        """FairFace 모델을 사용하여 얼굴 이미지로부터 인종, 성별, 나이를 예측"""
        # 이미지를 FairFace 모델의 입력 크기에 맞게 전처리
        trans = transforms.Compose([
            transforms.ToPILImage(),
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
        ])
        
        try:
            face_image = trans(face_image).unsqueeze(0).to(self.device)
        except ValueError:
            logging.error("이미지가 너무 작거나 손상됨, 예측 건너뜀.")
            return None
        
        # 예측 실행
        with torch.no_grad():
            outputs = self.model(face_image).cpu().numpy().squeeze()
        
        # 예측 결과를 바탕으로 인종, 성별, 나이를 추론
        race_pred = np.argmax(outputs[:4])  # 인종 예측
        gender_pred = np.argmax(outputs[7:9])  # 성별 예측
        age_pred = np.argmax(outputs[9:18])  # 나이 예측
        
        race_text = ['백인', '흑인', '아시아', '중동'][race_pred]
        gender_text, box_color = [('남성', (50, 100, 255)), ('여성', (255, 100, 50))][gender_pred]
        age_text = ['영아', '유아', '10대', '20대', '30대', '40대', '50대', '60대', '70+'][age_pred]
        
        # 예측 결과를 딕셔너리로 반환
        return {"race": race_text, "gender": gender_text, "box_color": box_color, "age": age_text}
        #
    #
#
# =========================
# 추상화: Model 관리자 클래스
# =========================
class ModelManager(ABC):
    @abstractmethod
    def __init__(self, model_path):
        """
        모델 매니저 클래스의 생성자. 
        
        이 메서드는 하위 클래스에서 모델 로드 및 초기화를 처리하도록 추상화되어 있음.
        
        하위 클래스에서 구체적 구현을 제공해야 함.
        """
        pass
        #
    #
    @abstractmethod
    def manage_prediction(self, image, image_path=None):
        """
        모델을 통해 예측을 관리하는 메서드.
        
        이 메서드는 하위 클래스에서 구체적 예측 로직을 구현하도록 추상화되어 있음.
        """
        pass
        #
    #
#
# =========================
# FaceDetector 관리자 클래스
# =========================
class FaceDetectors(ModelManager):
    def __init__(self, *detectors):
        """탐지기들을 받아 관리하는 클래스 생성자"""
        self.detectors = detectors  # 여러 얼굴 탐지기를 리스트로 저장
        #
    #
    def manage_prediction(self, image, image_path=None):
        """
        모든 탐지기를 사용하여 얼굴을 탐지하고, 비최대 억제(NMS)를 적용하여 중복된 얼굴 영역을 제거함.
        
        YOLO 탐지기의 경우 이미지 경로를, 나머지 탐지기의 경우 이미지를 입력으로 사용하여 얼굴을 탐지.
        """
        logging.info("얼굴 탐지 시작...")
        all_faces = []  # 모든 탐지 결과를 저장할 리스트
        for detector in self.detectors:
            try:
                # YOLO 탐지기의 경우 이미지 경로를 사용하여 탐지
                if isinstance(detector, YOLOFaceDetector) and image_path: 
                    faces = detector.predict(image_path)
                else:
                    # 그 외 탐지기의 경우 이미지를 사용하여 탐지
                    faces = detector.predict(image)
            except Exception as e:
                logging.error(f"얼굴 탐지 중 오류 발생: {e}")
                raise
            finally:
                logging.info(f"{detector} : {len(faces)}개의 얼굴 검출")
                #
            #
            all_faces.extend(faces)  # 탐지된 얼굴을 리스트에 추가
            #
        #
        logging.info(f"총 {len(all_faces)}개의 얼굴 검출.")
        #
        # 비최대 억제(NMS)를 적용하여 중복된 얼굴 영역을 제거한 결과 반환
        return self._apply_non_max_suppression(all_faces)
        #
    #
    @staticmethod
    def _apply_non_max_suppression(faces):
        """
        비최대 억제를 적용하여 중복된 얼굴 영역을 제거하는 함수.
        중복된 얼굴 영역을 제거하여 최종적으로 남은 얼굴 좌표만 반환.
        """
        if len(faces) == 0:
            return []  # 얼굴이 없을 경우 빈 리스트 반환
            #
        #
        # 얼굴 영역 좌표를 이용해 비최대 억제(NMS)를 적용
        boxes = np.array(faces).astype("float")
        pick = []  # 최종적으로 선택된 얼굴 영역을 저장할 리스트
        x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]  # 얼굴 좌표 분리
        area = (x2 - x1 + 1) * (y2 - y1 + 1)  # 얼굴 영역 계산
        idxs = np.argsort(y2)  # y2 값을 기준으로 얼굴 영역을 정렬
        #
        while len(idxs) > 0:
            last = len(idxs) - 1  # 마지막 인덱스
            i = idxs[last]  # 현재 얼굴 영역
            pick.append(i)  # 선택된 얼굴 영역 추가
            #
            # 나머지 얼굴 영역과 현재 얼굴 영역 간의 교차 영역 계산
            xx1 = np.maximum(x1[i], x1[idxs[:last]])
            yy1 = np.maximum(y1[i], y1[idxs[:last]])
            xx2 = np.minimum(x2[i], x2[idxs[:last]])
            yy2 = np.minimum(y2[i], y2[idxs[:last]])
            #
            w = np.maximum(0, xx2 - xx1 + 1)
            h = np.maximum(0, yy2 - yy1 + 1)
            overlap = (w * h) / area[idxs[:last]]  # 교차 비율 계산
            #
            # 교차 비율이 0.3을 넘는 얼굴 영역 제거
            idxs = np.delete(idxs, np.concatenate(([last], np.where(overlap > 0.3)[0])))
            #
        #
        return boxes[pick].astype("int").tolist()  # 최종 선택된 얼굴 영역 반환
        #
    #
#
# =========================
# FacePredictor 관리자 클래스
# =========================
class FacePredictors(ModelManager):
    def __init__(self, *predictors):
        """예측기들을 받아 관리하는 클래스 생성자"""
        self.predictors = predictors  # 여러 얼굴 예측기를 리스트로 저장
        #
    #
    def manage_prediction(self, image):
        """
        모든 예측기를 사용하여 얼굴 예측을 수행하고, 예측 결과를 통합하여 반환.
        """
        logging.info("얼굴 예측 시작...")
        all_predictions = {}  # 예측 결과를 저장할 딕셔너리
        for predictor in self.predictors:
            try:
                prediction = predictor.predict(image)  # 각 예측기를 사용하여 예측
            except Exception as e:
                logging.error(f"예측 중 오류 발생: {e}")
                continue  # 오류가 발생해도 다음 예측기로 계속 진행
            all_predictions.update(prediction)  # 예측 결과를 통합
        logging.info(f"예측 결과: {all_predictions}")
        return all_predictions  # 최종 예측 결과 반환
# =========================
# 얼굴 인식 시스템 클래스
# 기존의 advanced project 의 로직
# =========================
class AiSystem:
    def __init__(self, config, detector_manager, predictor_manager):
        """
        얼굴 인식 시스템 초기화. config 설정, 탐지기 및 예측기 관리자를 초기화함.
        
        :param config: 시스템 설정 정보
        :param detector_manager: 얼굴 탐지기 관리자
        :param predictor_manager: 얼굴 예측기 관리자
        """
        self.config = config
        self.detector_manager = detector_manager
        self.predictor_manager = predictor_manager
        #
    #
    def process_image(self, image_path, target_encodings):
        """
        이미지를 처리하고 얼굴 탐지 및 예측을 수행한 후 결과를 저장.
        
        :param image_path: 처리할 이미지 경로
        :param target_encodings: 타겟 얼굴 인코딩
        """
        try:
            image_rgb, faces = self._detect_faces(image_path)  # 얼굴 탐지
            predictions, face_cnt, race_cnt, male_cnt = self._complicate_predictions(image_rgb, faces, target_encodings)  # 얼굴 예측
            result_image = self._draw_results(image_rgb, predictions, face_cnt, male_cnt, race_cnt)  # 결과 그리기
            self._save_results(image_path, result_image, predictions)  # 결과 저장
        except Exception as e:
            logging.error(f"이미지 처리 중 오류 발생: {e}")
        #
    #
    def _detect_faces(self, image_path):
        """
        이미지에서 얼굴을 탐지하는 메서드.
        
        :param image_path: 이미지 경로
        :return: RGB 이미지 및 얼굴 좌표
        """
        try:
            image = cv2.imread(image_path)  # 이미지 읽기
            if image is None: 
                raise ValueError(f"이미지를 읽을 수 없습니다: {image_path}")
            image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)  # RGB로 변환
            faces = self.detector_manager.manage_prediction(image_rgb, image_path)  # 얼굴 탐지
            logging.info(f"얼굴 탐지 완료: {len(faces)}명")
            return image_rgb, faces  # RGB 이미지와 얼굴 좌표 반환
        except Exception as e:
            logging.error(f"얼굴 탐지 중 오류 발생: {e}")
            raise
        #
    #
    def _complicate_predictions(self, image_rgb, faces, target_encodings):
        """
        얼굴 예측 결과를 집계하여 반환.
        
        :param image_rgb: RGB로 변환된 이미지
        :param faces: 얼굴 좌표
        :param target_encodings: 타겟 얼굴 인코딩
        :return: 예측 결과, 얼굴 개수, 인종별 개수, 남성 개수
        """
        predictions = []
        face_cnt = 0
        race_cnt = {'백인': 0, '흑인': 0, '아시아': 0, '중동': 0}
        male_cnt = 0
        for face in faces:
            prediction = self._predict_face(image_rgb, face, target_encodings)
            if prediction:
                predictions.append(prediction)
                face_cnt += 1
                race_text, gender_text = prediction[4], prediction[5]
                race_cnt[race_text] += 1
                if gender_text == '남성':
                    male_cnt += 1
                    #
                #
            #
        #
        return predictions, face_cnt, race_cnt, male_cnt
        #
    #
    def _predict_face(self, image_rgb, face, target_encodings):
        """
        단일 얼굴에 대해 예측을 수행하고 결과를 반환.
        
        :param image_rgb: RGB 이미지
        :param face: 얼굴 좌표
        :param target_encodings: 타겟 얼굴 인코딩
        :return: 얼굴 예측 결과
        """
        try:
            x, y, x2, y2 = face  # 얼굴 좌표
            face_image = image_rgb[y:y2, x:x2]  # 얼굴 이미지
            encodings = face_recognition.face_encodings(image_rgb, [(y, x + (x2 - x), y + (y2 - y), x)])  # 얼굴 인코딩
            if not encodings:
                logging.warning(f"얼굴 인코딩 실패: {face}")
                return None
            prediction_result = self.predictor_manager.manage_prediction(face_image)  # 얼굴 예측
            race_text = prediction_result.get("race", "알 수 없음")  # 인종
            gender_text = prediction_result.get("gender", "알 수 없음")  # 성별
            box_color = prediction_result.get("box_color", (0, 0, 0))  # 박스 색상
            age_text = prediction_result.get("age", "알 수 없음")  # 나이
            is_gaka = any(face_recognition.compare_faces(target_encodings, encodings[0], tolerance=0.3))  # 가카 여부
            prediction_text = '가카!' if is_gaka and gender_text == '남성' else age_text  # 예측 텍스트
            return x, y, x2 - x, y2 - y, race_text, gender_text, box_color, prediction_text
        except Exception as e:
            logging.error(f"단일 얼굴 처리 중 오류 발생: {e}")
            return None
        #
    #
    def _draw_results(self, image_rgb, predictions, face_cnt, male_cnt, race_cnt):
        """
        예측 결과를 이미지에 그려서 반환.
        
        :param image_rgb: RGB 이미지
        :param predictions: 얼굴 예측 결과
        :param face_cnt: 검출된 얼굴 수
        :param male_cnt: 남성 수
        :param race_cnt: 인종별 얼굴 수
        :return: 결과가 그려진 이미지
        """
        font_size = max(12, int(image_rgb.shape[1] / 200))  # 폰트 크기 설정
        image_rgb, scale, top, left = resize_image_with_padding(image_rgb, 512)  # 이미지 리사이즈
        for x, y, w, h, _, _, box_color, prediction_text in predictions: 
            x = int(x * scale) + left
            y = int(y * scale) + top
            w = int(w * scale)
            h = int(h * scale)
            image_rgb = draw_korean_text(self.config, image_rgb, prediction_text, (x, y), 15, font_color=(0, 0, 0), background_color=box_color)
            image_rgb = cv2.rectangle(image_rgb, (x, y), (x + w, y + h), box_color, 2)
        info_text = f"검출된 인원 수: {face_cnt}명\n남성: {male_cnt}명\n여성: {face_cnt - male_cnt}명\n"
        race_info = "\n".join([f"{race}: {count}명" for race, count in race_cnt.items() if count > 0])
        image_rgb = extend_image_with_text(self.config, image_rgb, info_text + race_info, font_size)
        return image_rgb
        #
    #
    def _save_results(self, image_path, image_rgb, predictions):
        """
        처리된 결과 이미지를 저장하고 메타데이터를 추가함.
        
        :param image_path: 원본 이미지 경로
        :param image_rgb: 처리된 이미지
        :param predictions: 예측 결과
        """
        try:
            output_path = os.path.join(self.config['results_folder'], os.path.basename(image_path))  # 결과 이미지 경로
            cv2.imwrite(output_path, cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR))  # 이미지 저장
            logging.info(f"이미지 분석 결과 저장: {output_path}") 
            gaka_detected = any("가카" in pred[7] for pred in predictions)  # 가카 여부 확인
            detection_folder = "detection_target" if gaka_detected else "detection_non_target"  # 타겟 여부 폴더 설정
            output_folder = os.path.join(self.config['results_folder'], detection_folder)  # 결과 폴더 생성
            copy_image_and_add_metadata(image_path, output_folder)  # 이미지 복사 및 메타데이터 추가
            logging.info(f"메타데이터 추가된 이미지 저장: {output_folder}") 
        except Exception as e:
            logging.error(f"결과 저장 중 오류 발생: {e}")
        #
    #
#
# =========================
# 얼굴 인식 시스템 클래스 for Django
# =========================
class ForDjango(AiSystem):
    def __init__(self, config, detector_manager, predictor_manager):
        """
        Django 환경에서 동작할 얼굴 인식 시스템 초기화.
        
        :param config: 시스템 설정 정보
        :param detector_manager: 얼굴 탐지기 관리자
        :param predictor_manager: 얼굴 예측기 관리자
        """
        super().__init__(config, detector_manager, predictor_manager)
        #
    #
    def process_image(self, image_path, target_encodings):
        """
        이미지에서 얼굴을 탐지하고 결과를 저장하는 메서드.
        
        :param image_path: 처리할 이미지 경로
        :param target_encodings: 타겟 얼굴 인코딩
        :return: Django에서 사용할 수 있는 이미지 경로
        """
        try:
            image_rgb, faces = self._detect_faces(image_path)  # 얼굴 탐지
            if self.predictor_manager:  # 예측기가 설정된 경우
                predictions, face_cnt, race_cnt, male_cnt = self._complicate_predictions(image_rgb, faces, target_encodings)  # 얼굴 예측
            else:
                predictions, face_cnt, race_cnt, male_cnt = faces, f'{len(faces)}', None, None
            result_image = self._draw_results(image_rgb, predictions, face_cnt, male_cnt, race_cnt)  # 결과 그리기
            output_path = self._save_results(image_path, result_image, predictions)  # 결과 저장
            logging.info(f"이미지 분석 결과 저장: {image_path}")
            logging.info(f"이미지 분석 결과 저장: {output_path}")
            
            # Django에서 사용할 수 있는 이미지 경로로 변환
            django_path = os.path.join('pybo/answer_image', os.path.basename(output_path))
            return django_path
        except Exception as e:
            logging.error(f"이미지 처리 중 오류 발생: {e}")
        #
    #
    def _draw_results(self, image_rgb, predictions, face_cnt, male_cnt, race_cnt):
        """
        예측 결과를 이미지에 그리는 메서드.
        
        :param image_rgb: RGB로 변환된 이미지
        :param predictions: 얼굴 예측 결과
        :param face_cnt: 얼굴 개수
        :param male_cnt: 남성 수
        :param race_cnt: 인종별 얼굴 수
        :return: 예측 결과가 그려진 이미지
        """
        font_size = max(12, int(image_rgb.shape[1] / 200))  # 폰트 크기 설정
        image_rgb, scale, top, left = resize_image_with_padding(image_rgb, 512)  # 이미지 리사이즈
        #
        try:
            # 각 얼굴에 대해 예측 결과를 그리기
            for x, y, w, h, _, _, box_color, _ in predictions:
                x = int(x * scale) + left
                y = int(y * scale) + top
                w = int(w * scale)
                h = int(h * scale)
                image_rgb = cv2.rectangle(image_rgb, (x, y), (x + w, y + h), box_color, 2)
            #
            # 인식된 얼굴 정보 텍스트 생성
            info_text = f"검출된 인원 수: {face_cnt}명\n남성: {male_cnt}명\n여성: {face_cnt - male_cnt}명\n"
            race_info = "\n".join([f"{race}: {count}명" for race, count in race_cnt.items() if count > 0])
        #
        except Exception as e:
            # 예측 결과가 없을 경우 기본 결과 그리기
            for x, y, x2, y2 in predictions:
                w, h = x2 - x, y2 - y
                x = int(x * scale) + left
                y = int(y * scale) + top
                w = int(w * scale)
                h = int(h * scale)
                image_rgb = cv2.rectangle(image_rgb, (x, y), (x + w, y + h), (0, 255, 0), 2)
            #
            info_text = f"검출된 인원 수: {face_cnt}명\n"
            race_info = ""
        #
        # 텍스트와 결과를 이미지 위에 확장해서 추가
        image_rgb = extend_image_with_text(self.config, image_rgb, info_text + race_info, font_size)
        return image_rgb
        #
    #
    def _save_results(self, image_path, result_image, predictions=None):
        """
        결과 이미지를 저장하는 메서드.
        
        :param image_path: 원본 이미지 경로
        :param result_image: 처리된 결과 이미지
        :param predictions: 예측 결과 (Optional)
        :return: 저장된 결과 이미지 경로
        """
        os.makedirs(self.config['results_folder'], exist_ok=True)  # 결과 폴더 생성
        output_path = os.path.join(self.config['results_folder'], os.path.basename(image_path))  # 결과 이미지 경로
        cv2.imwrite(output_path, cv2.cvtColor(result_image, cv2.COLOR_RGB2BGR))  # 이미지 저장
        logging.info(f"이미지 분석 결과 저장: {output_path}")  
        return output_path
        #
    #
#
# =========================
# Django 시스템 설정 데코레이터
# =========================
def setup_django_system(func):
    """
    설정 및 시스템 초기화를 처리하는 데코레이터.
    
    Django에서 AI 시스템을 사용하기 위한 설정을 초기화하고,
    사용자 요청에 따라 탐지기 및 예측기를 설정하여 시스템을 실행.
    """
    def wrapper(request, image_path, *args, **kwargs):
        # 경고 및 로깅 설정
        setup_warnings_and_logging()
        #
        # 설정 파일 로드
        base_dir = os.path.join(Path(__file__).resolve().parent, 'ai_files')
        django_media_dir = os.path.join(Path(__file__).resolve().parent.parent.parent, 'media/pybo/answer_image')
        config = {
            "dlib_model_path": os.path.join(base_dir, 'ai_models', 'DilbCNN', 'mmod_human_face_detector.dat'),
            "yolo_model_path": os.path.join(base_dir, 'ai_models', 'YOLOv8', 'yolov8n-face.pt'),
            "fair_face_model_path": os.path.join(base_dir, 'ai_models', 'FairFace', 'resnet34_fair_face_4.pt'),
            "image_folder": os.path.join(base_dir, 'image_test', 'test_park_mind_problem'),
            "pickle_path": os.path.join(base_dir, 'embedings', 'FaceRecognition(ResNet34).pkl'),
            "font_path": os.path.join(base_dir, 'fonts', 'NanumGothic.ttf'),
            "results_folder": django_media_dir,
        }
        #
        # 사용자가 선택한 탐지기 및 예측기를 설정
        selected_detectors = request.POST.getlist('detectors')  # 여러 탐지기 선택 가능
        selected_predictors = request.POST.getlist('predictors')  # 여러 예측기 선택 가능
        #
        # 얼굴 탐지기 설정
        detectors = []
        if 'dlib' in selected_detectors:
            detectors.append(DlibFaceDetector(config['dlib_model_path']))
        if 'yolo' in selected_detectors:
            detectors.append(YOLOFaceDetector(config['yolo_model_path']))
        if 'mtcnn' in selected_detectors:
            detectors.append(MTCNNFaceDetector())
        #
        # 탐지기가 선택되지 않은 경우
        if not detectors:
            logging.warning("탐지기가 선택되지 않았습니다. 탐지 작업을 건너뜁니다.")
            detector_manager = None
        else:
            detector_manager = FaceDetectors(*detectors)
        #
        # 얼굴 예측기 설정
        predictors = []
        if 'fairface' in selected_predictors:
            predictors.append(FairFacePredictor(config['fair_face_model_path']))
        #
        # 예측기가 선택되지 않은 경우
        if not predictors:
            logging.warning("예측기가 선택되지 않았습니다. 예측 작업을 건너뜁니다.")
            predictor_manager = None
        else:
            predictor_manager = FacePredictors(*predictors)
        #
        # 얼굴 인식 시스템 생성
        ai_system = ForDjango(config, detector_manager, predictor_manager)
        #
        # 타겟 얼굴 인코딩 로드
        with open(config['pickle_path'], 'rb') as f:
            target_encodings = np.array(pickle.load(f))
        #
        # 함수 실행
        return func(request, image_path, ai_system, target_encodings, *args, **kwargs)
    #
    return wrapper
    #
#
# =========================
# 메인 실행 모듈
# =========================
def main():
    """
    메인 함수: 시스템 설정 및 여러 이미지 처리.
    
    여러 이미지를 처리하고 얼굴 탐지 및 예측 결과를 저장.
    """
    # 경고 및 로깅 설정
    setup_warnings_and_logging()
    #
    base_dir = os.path.join(Path(__file__).resolve().parent, 'ai_files')
    config = {
        "dlib_model_path": os.path.join(base_dir, 'ai_models', 'DilbCNN', 'mmod_human_face_detector.dat'),
        "yolo_model_path": os.path.join(base_dir, 'ai_models', 'YOLOv8', 'yolov8n-face.pt'),
        "fair_face_model_path": os.path.join(base_dir, 'ai_models', 'FairFace', 'resnet34_fair_face_4.pt'),
        "image_folder": os.path.join(base_dir, 'image_test', 'test_park_mind_problem'),
        "pickle_path": os.path.join(base_dir, 'embedings', 'FaceRecognition(ResNet34).pkl'),
        "font_path": os.path.join(base_dir, 'fonts', 'NanumGothic.ttf'),
        "results_folder": os.path.join(base_dir, 'results_test')
    }
    #
    # 얼굴 탐지기 생성
    detector_manager = FaceDetectors(
        DlibFaceDetector(config['dlib_model_path']),
        YOLOFaceDetector(config['yolo_model_path']),
        MTCNNFaceDetector()
    )
    #
    # 얼굴 예측기 생성
    predictor_manager = FacePredictors(
        FairFacePredictor(config['fair_face_model_path'])
    )
    #
    # 얼굴 인식 시스템 생성
    ai_system = AiSystem(config, detector_manager, predictor_manager)
    #
    # 타겟 얼굴 인코딩 로드
    with open(config['pickle_path'], 'rb') as f:
        target_encodings = np.array(pickle.load(f))
    #
    # 이미지 폴더에서 이미지 로드
    image_list = [f for f in os.listdir(config['image_folder']) if f.lower().endswith(('png', 'jpg', 'jpeg'))]
    #
    # 모든 이미지 처리
    for image in image_list:
        image_path = os.path.join(config['image_folder'], image)
        logging.info(f"이미지 처리 시작: {image_path}")
        output_path = ai_system.process_image(image_path, target_encodings)
        logging.info(f"이미지 처리 완료: {output_path}")
    #
#
if __name__ == "__main__":
    main()
#

