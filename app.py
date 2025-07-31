from flask import Flask, render_template, request, redirect, url_for, send_file
from flask_pymongo import PyMongo
from bson.objectid import ObjectId
from datetime import datetime
from dotenv import load_dotenv
import os
import io
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from collections import defaultdict

load_dotenv()

app = Flask(__name__)
app.config['MONGO_URI'] = os.getenv("MONGO_URI")
mongo = PyMongo(app)

participantes_collection = mongo.db.participantes
asistencias_collection = mongo.db.asistencias

@app.route('/')
def index():
    hoy = datetime.today().strftime('%Y-%m-%d')
    participantes = list(participantes_collection.find({'activo': True}))
    fechas_registradas = asistencias_collection.distinct('fecha')
    return render_template('index.html', participantes=participantes, hoy=hoy, fecha=hoy, fechas_registradas=fechas_registradas)

@app.route('/registrar_asistencia', methods=['POST'])
def registrar_asistencia():
    fecha_str = request.form['fecha']
    presentes = request.form.getlist('asistencia')  # lista de IDs como strings

    try:
        fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date()
    except ValueError:
        return "Fecha inválida", 400

    # Eliminar asistencias previas de esa fecha
    asistencias_collection.delete_many({'fecha': fecha_str})

    participantes = list(participantes_collection.find({'activo': True}))
    for p in participantes:
        participante_id_str = str(p['_id'])
        presente = participante_id_str in presentes

        asistencia = {
            'fecha': fecha_str,
            'participante_id': p['_id'],  # importante: ObjectId
            'presente_catequesis': presente,
            'presente_misa': False  # si manejas misa en otro form, puedes omitir o modificar esto
        }

        asistencias_collection.insert_one(asistencia)

    return redirect(url_for('index'))

@app.route('/nuevo_participante')
def nuevo_participante():
    return render_template('nuevo_participante.html')

@app.route('/guardar_participante', methods=['POST'])
def guardar_participante():
    participante = {
        'nombre': request.form['nombre'],
        'edad': int(request.form['edad']),
        'grupo': request.form['grupo'],
        'contacto': request.form['contacto'],
        'activo': True
    }
    participantes_collection.insert_one(participante)
    return redirect('/')

@app.route('/editar_participante/<id>')
def editar_participante(id):
    participante = participantes_collection.find_one({'_id': ObjectId(id)})
    return render_template('editar_participante.html', participante=participante)

@app.route('/actualizar_participante/<id>', methods=['POST'])
def actualizar_participante(id):
    participantes_collection.update_one(
        {'_id': ObjectId(id)},
        {'$set': {
            'nombre': request.form['nombre'],
            'edad': int(request.form['edad']),
            'grupo': request.form['grupo'],
            'contacto': request.form['contacto']
        }}
    )
    return redirect(f'/historial/{id}')

@app.route('/eliminar_participante/<id>', methods=['POST'])
def eliminar_participante(id):
    participantes_collection.update_one({'_id': ObjectId(id)}, {'$set': {'activo': False}})
    return redirect('/')

@app.route('/historial/<id>')
def historial(id):
    try:
        participante = participantes_collection.find_one({'_id': ObjectId(id)})
        if not participante:
            return "Participante no encontrado", 404

        # Filtrar asistencias usando ObjectId
        asistencias = list(asistencias_collection.find({'participante_id': ObjectId(id)}))

        total_asistencias = sum(1 for a in asistencias if a.get('presente_catequesis') or a.get('presente_misa'))

        return render_template('historial.html',
                               participante=participante,
                               asistencias=asistencias,
                               total_asistencias=total_asistencias)
    except Exception as e:
        return f"Error: {str(e)}", 500

@app.route('/editar_asistencia/<fecha>', methods=['GET', 'POST'])
def editar_asistencia(fecha):
    participantes = list(participantes_collection.find({'activo': True}))
    if request.method == 'POST':
        presentes_catequesis = request.form.getlist('presente_catequesis')
        presentes_misa = request.form.getlist('presente_misa')
        observaciones_catequesis = request.form.getlist('observacion_catequesis')
        observaciones_misa = request.form.getlist('observacion_misa')

        for idx, p in enumerate(participantes):
            p_id = str(p['_id'])
            presente_cat = p_id in presentes_catequesis
            presente_mi = p_id in presentes_misa
            observ_cat = observaciones_catequesis[idx] if idx < len(observaciones_catequesis) else ""
            observ_mi = observaciones_misa[idx] if idx < len(observaciones_misa) else ""

            asistencia = asistencias_collection.find_one({'fecha': fecha, 'participante_id': p_id})
            if asistencia:
                asistencias_collection.update_one(
                    {'_id': asistencia['_id']},
                    {'$set': {
                        'presente_catequesis': presente_cat,
                        'presente_misa': presente_mi,
                        'observacion_catequesis': observ_cat,
                        'observacion_misa': observ_mi
                    }}
                )
            else:
                asistencias_collection.insert_one({
                    'fecha': fecha,
                    'participante_id': p_id,
                    'presente_catequesis': presente_cat,
                    'presente_misa': presente_mi,
                    'observacion_catequesis': observ_cat,
                    'observacion_misa': observ_mi
                })

        return redirect(url_for('index'))

    asistencias = {a['participante_id']: a for a in asistencias_collection.find({'fecha': fecha})}
    return render_template('editar_asistencia.html', fecha=fecha, participantes=participantes, asistencias=asistencias)

@app.route('/porcentajes')
def porcentajes():
    total_dias = len(asistencias_collection.distinct('fecha'))
    participantes = list(participantes_collection.find({'activo': True}))
    porcentaje_list = []
    for p in participantes:
        p_id = str(p['_id'])
        catequesis_count = asistencias_collection.count_documents({'participante_id': p_id, 'presente_catequesis': True})
        misa_count = asistencias_collection.count_documents({'participante_id': p_id, 'presente_misa': True})
        porcentaje_catequesis = (catequesis_count / total_dias * 100) if total_dias > 0 else 0
        porcentaje_misa = (misa_count / total_dias * 100) if total_dias > 0 else 0
        porcentaje_list.append({
            'id': p_id,
            'nombre': p['nombre'],
            'grupo': p['grupo'],
            'porcentaje_catequesis': round(porcentaje_catequesis, 2),
            'porcentaje_misa': round(porcentaje_misa, 2)
        })
    return render_template('porcentajes.html', participantes=porcentaje_list, total_dias=total_dias)

@app.route('/descargar_pdf', methods=['POST'])
def descargar_pdf():
    resultados = list(asistencias_collection.find({}))
    participantes_map = {str(p['_id']): p for p in participantes_collection.find()}

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer)
    styles = getSampleStyleSheet()
    elements = []
    elements.append(Paragraph("Reporte de Asistencia (Catequesis y Misa)", styles['Title']))
    elements.append(Spacer(1, 12))

    if not resultados:
        elements.append(Paragraph("No hay registros de asistencia.", styles['Normal']))
    else:
        asistencias_por_fecha = defaultdict(list)
        for r in resultados:
            asistencias_por_fecha[r['fecha']].append(r)

        for fecha, registros in sorted(asistencias_por_fecha.items(), reverse=True):
            elements.append(Paragraph(f"Fecha: {fecha}", styles['Heading2']))
            data = [["Nombre", "Grupo", "Catequesis", "Observ. Catequesis", "Misa", "Observ. Misa"]]
            for r in registros:
                p = participantes_map.get(r['participante_id'])
                if not p:
                    continue
                catequesis_txt = "Sí" if r.get('presente_catequesis') else "No"
                misa_txt = "Sí" if r.get('presente_misa') else "No"
                data.append([
                    p['nombre'],
                    p['grupo'],
                    catequesis_txt,
                    r.get('observacion_catequesis', 'Sin observación'),
                    misa_txt,
                    r.get('observacion_misa', 'Sin observación')
                ])

            tabla = Table(data, hAlign='LEFT')
            tabla.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3b82f6')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('GRID', (0, 0), (-1, -1), 1, colors.gray),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')
            ]))
            elements.append(tabla)
            elements.append(Spacer(1, 24))

    doc.build(elements)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="reporte_asistencia.pdf", mimetype='application/pdf')

if __name__ == '__main__':
    app.run(debug=True)
