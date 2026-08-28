#!/usr/bin/env python3
"""
Ejemplo: Conteo de Aforo en Autopista
======================================

Este ejemplo muestra cómo configurar el sistema para
contar vehículos en una autopista con vista frontal.

Características:
- Línea de conteo horizontal
- Múltiples carriles
- Alta velocidad de vehículos
"""

import sys
import os

# Agregar directorio padre al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.detector import VehicleDetector
from src.tracker import VehicleTracker
from src.counter import BidirectionalCounter
from src.visualizer import Visualizer
from src.video_processor import VideoProcessor
import cv2


def main():
    print("=" * 60)
    print("EJEMPLO: CONTEO EN AUTOPISTA")
    print("=" * 60)
    
    # Configuración para autopista
    VIDEO_PATH = "input/highway_video.mp4"
    OUTPUT_PATH = "results/highway_output.mp4"
    
    # 1. Inicializar componentes
    print("\n1. Inicializando detector...")
    detector = VehicleDetector(
        model_path='models/yolov8n.pt',
        confidence_threshold=0.45,  # Más alto para reducir falsos positivos
        input_size=640
    )
    
    print("2. Inicializando tracker...")
    tracker = VehicleTracker(
        max_age=40,  # Mayor para vehículos rápidos
        min_hits=3,
        iou_threshold=0.3
    )
    
    print("3. Inicializando contador...")
    counter = BidirectionalCounter(
        line_type='horizontal',
        # line_position se configurará automáticamente
    )
    
    print("4. Inicializando visualizador...")
    visualizer = Visualizer(
        show_labels=True,
        show_trajectories=True,
        show_ids=True
    )
    
    # 2. Configurar procesador
    processor = VideoProcessor(
        detector=detector,
        tracker=tracker,
        counter=counter,
        visualizer=visualizer,
        skip_frames=0  # Procesar todos los frames
    )
    
    # 3. Abrir video
    print(f"\n5. Abriendo video: {VIDEO_PATH}")
    cap = cv2.VideoCapture(VIDEO_PATH)
    
    if not cap.isOpened():
        print(f"ERROR: No se pudo abrir el video: {VIDEO_PATH}")
        print("Por favor, coloca un video en la carpeta 'input/'")
        return
    
    # Obtener propiedades del video
    fps = int(cap.get(cv2.CAP_PROP_FPS))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    print(f"   Resolución: {width}x{height}")
    print(f"   FPS: {fps}")
    print(f"   Frames totales: {total_frames}")
    
    # 4. Configurar línea de conteo (centro del frame)
    counter.set_counting_line(
        line_type='horizontal',
        y=height // 2,  # Línea en el centro
        frame_shape=(height, width)
    )
    
    # 5. Preparar escritor de video
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(OUTPUT_PATH, fourcc, fps, (width, height))
    
    # 6. Procesar video
    print("\n6. Procesando video...")
    print("   Presiona 'q' para salir")
    
    frame_count = 0
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        # Procesar frame
        processed_frame, frame_data = processor.process_frame(frame, frame_count)
        
        # Guardar frame
        out.write(processed_frame)
        
        # Mostrar frame
        cv2.imshow('Aforo en Autopista', processed_frame)
        
        # Log cada 30 frames
        if frame_count % 30 == 0:
            counts = counter.get_counts()
            print(f"   Frame {frame_count}/{total_frames} - "
                  f"Entrada: {counts['in']}, Salida: {counts['out']}")
        
        frame_count += 1
        
        # Salir con 'q'
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    
    # 7. Liberar recursos
    cap.release()
    out.release()
    cv2.destroyAllWindows()
    
    # 8. Mostrar resultados
    print("\n" + "=" * 60)
    print("RESULTADOS FINALES")
    print("=" * 60)
    
    counts = counter.get_counts()
    detailed = counter.get_detailed_counts()
    
    print(f"Frames procesados: {frame_count}")
    print(f"\nConteo Total:")
    print(f"  Vehículos entrando: {counts['in']}")
    print(f"  Vehículos saliendo: {counts['out']}")
    print(f"  Total: {counts['total']}")
    print(f"  Flujo neto: {counts['net_flow']}")
    
    if detailed:
        print(f"\nPor tipo de vehículo:")
        for vtype, vcounts in detailed.items():
            print(f"  {vtype.upper()}: "
                  f"Entrada={vcounts['in']}, "
                  f"Salida={vcounts['out']}, "
                  f"Total={vcounts['total']}")
    
    print(f"\nVideo guardado en: {OUTPUT_PATH}")
    print("=" * 60)


if __name__ == '__main__':
    main()
