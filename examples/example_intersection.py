#!/usr/bin/env python3
"""
Ejemplo: Conteo en Intersección
================================

Este ejemplo muestra cómo configurar múltiples líneas de conteo
para una intersección con 4 direcciones.

Características:
- Múltiples líneas de conteo
- Análisis por dirección
- Flujo de tráfico en intersección
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.detector import VehicleDetector
from src.tracker import VehicleTracker
from src.counter import BidirectionalCounter
from src.visualizer import Visualizer
import cv2
import numpy as np


def main():
    print("=" * 60)
    print("EJEMPLO: CONTEO EN INTERSECCIÓN")
    print("=" * 60)
    
    VIDEO_PATH = "input/intersection_video.mp4"
    OUTPUT_PATH = "results/intersection_output.mp4"
    
    # 1. Inicializar componentes
    detector = VehicleDetector(
        model_path='models/yolov8n.pt',
        confidence_threshold=0.4,
        input_size=640
    )
    
    tracker = VehicleTracker(
        max_age=30,
        min_hits=3,
        iou_threshold=0.3
    )
    
    # En una intersección, podríamos usar múltiples contadores
    # Para este ejemplo, usamos uno principal
    counter_north_south = BidirectionalCounter(line_type='horizontal')
    counter_east_west = BidirectionalCounter(line_type='vertical')
    
    visualizer = Visualizer(
        show_labels=True,
        show_trajectories=True,
        show_ids=True
    )
    
    # 2. Abrir video
    cap = cv2.VideoCapture(VIDEO_PATH)
    
    if not cap.isOpened():
        print(f"ERROR: No se pudo abrir el video")
        print(f"Coloca un video de intersección en: {VIDEO_PATH}")
        return
    
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = int(cap.get(cv2.CAP_PROP_FPS))
    
    # 3. Configurar líneas de conteo
    # Línea Norte-Sur (horizontal en el centro)
    counter_north_south.set_counting_line(
        line_type='horizontal',
        y=height // 2,
        frame_shape=(height, width)
    )
    
    # Línea Este-Oeste (vertical en el centro)
    counter_east_west.set_counting_line(
        line_type='vertical',
        x=width // 2,
        frame_shape=(height, width)
    )
    
    # 4. Preparar salida
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(OUTPUT_PATH, fourcc, fps, (width, height))
    
    # 5. Procesar video
    print("\nProcesando video...")
    frame_count = 0
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        # Detectar
        detections, _ = detector.detect(frame)
        
        # Rastrear
        tracks = tracker.update(detections)
        
        # Contar en ambas direcciones
        crossings_ns = counter_north_south.update(tracks)
        crossings_ew = counter_east_west.update(tracks)
        
        # Visualizar
        output_frame = visualizer.draw_tracks(frame, tracks)
        
        # Dibujar ambas líneas
        line_ns = counter_north_south.get_line_coordinates()
        line_ew = counter_east_west.get_line_coordinates()
        
        if line_ns:
            output_frame = visualizer.draw_counting_line(
                output_frame,
                line_ns,
                line_color=(0, 255, 255)  # Amarillo
            )
        
        if line_ew:
            output_frame = visualizer.draw_counting_line(
                output_frame,
                line_ew,
                line_color=(255, 0, 255)  # Magenta
            )
        
        # Estadísticas personalizadas
        counts_ns = counter_north_south.get_counts()
        counts_ew = counter_east_west.get_counts()
        
        # Dibujar estadísticas
        stats_text = [
            "=== INTERSECCION ===",
            f"Norte-Sur: {counts_ns['total']}",
            f"  Norte: {counts_ns['in']}",
            f"  Sur: {counts_ns['out']}",
            f"Este-Oeste: {counts_ew['total']}",
            f"  Este: {counts_ew['in']}",
            f"  Oeste: {counts_ew['out']}"
        ]
        
        y_offset = 30
        for line in stats_text:
            cv2.putText(
                output_frame,
                line,
                (10, y_offset),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2
            )
            y_offset += 25
        
        # Guardar y mostrar
        out.write(output_frame)
        cv2.imshow('Intersección', output_frame)
        
        if frame_count % 30 == 0:
            print(f"Frame {frame_count} - "
                  f"NS: {counts_ns['total']}, "
                  f"EW: {counts_ew['total']}")
        
        frame_count += 1
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    
    # 6. Resultados
    cap.release()
    out.release()
    cv2.destroyAllWindows()
    
    print("\n" + "=" * 60)
    print("RESULTADOS FINALES")
    print("=" * 60)
    
    counts_ns = counter_north_south.get_counts()
    counts_ew = counter_east_west.get_counts()
    
    print(f"\nNorte-Sur:")
    print(f"  Dirección Norte: {counts_ns['in']}")
    print(f"  Dirección Sur: {counts_ns['out']}")
    print(f"  Total: {counts_ns['total']}")
    
    print(f"\nEste-Oeste:")
    print(f"  Dirección Este: {counts_ew['in']}")
    print(f"  Dirección Oeste: {counts_ew['out']}")
    print(f"  Total: {counts_ew['total']}")
    
    print(f"\nTotal general: {counts_ns['total'] + counts_ew['total']}")
    print(f"\nVideo guardado en: {OUTPUT_PATH}")
    print("=" * 60)


if __name__ == '__main__':
    main()
