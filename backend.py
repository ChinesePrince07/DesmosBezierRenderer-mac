import json
from flask import Flask, jsonify
from flask_cors import CORS
from flask import request
from flask import render_template
from werkzeug.utils import secure_filename

from PIL import Image
import numpy as np
import potrace
import cv2

import multiprocessing
from time import time
import os
import sys
import getopt
import traceback
import webbrowser
from threading import Timer


app = Flask(__name__, template_folder='frontend')
CORS(app)
PORT = int(os.environ.get('PORT', 5000))
HOST = os.environ.get('HOST', '127.0.0.1')


FRAME_DIR = 'frames' # The folder where the frames are stored relative to this file
FILE_EXT = 'png' # Extension for frame files
COLOUR = '#2464b4' # Hex value of colour for graph output	
SCREENSHOT_SIZE = [ None, None ] # [width, height] for downloaded images
SCREENSHOT_FORMAT = 'png' # Format to use when downloading images
OPEN_BROWSER = True # Open default browser automatically

BILATERAL_FILTER = False # Reduce number of lines with bilateral filter
DOWNLOAD_IMAGES = False # Download each rendered frame automatically (works best in firefox)
USE_L2_GRADIENT = False # Creates less edges but is still accurate (leads to faster renders)
SHOW_GRID = True # Show the grid in the background while rendering

frame = multiprocessing.Value('i', 0)
height = multiprocessing.Value('i', 0, lock = False)
width = multiprocessing.Value('i', 0, lock = False)
frame_latex = 0


def help():
    print('backend.py -f <source> -e <extension> -c <colour> -b -d -l -g --yes --no-browser --size <widthxheight> --format <extension>\n')
    print('\t-h\t\t\tGet help\n')
    print('-Options\n')
    print('\t-f <source>\t\tThe directory from which the frames are stored (e.g. frames)')
    print('\t-e <extension>\t\tThe extension of the frame files (e.g. png)')
    print('\t-c <colour>\t\tThe colour of the lines to be drawn (e.g. #2464b4)')
    print('\t-b\t\t\tReduce number of lines with bilateral filter for simpler renders')
    print('\t-d\t\t\tDownload rendered frames automatically')
    print('\t-l\t\t\tReduce number of lines with L2 gradient for quicker renders')
    print('\t-g\t\t\tHide the grid in the background of the graph\n')
    print('\t--yes\t\t\tAgree to EULA without input prompt')
    print('\t--no-browser\t\tRun renderer server without opening a web browser')
    print('\t--size <widthxheight>\tDimensions for downloaded images (e.g. 3840x2160)')
    print('\t--format <extension>\tSpecify format when downloading frames: "svg" or "png" (default is "png")')


def get_contours(filename, nudge = .33):
    image = cv2.imread(filename)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    if BILATERAL_FILTER:
        median = max(10, min(245, np.median(gray)))
        lower = int(max(0, (1 - nudge) * median))
        upper = int(min(255, (1 + nudge) * median))
        filtered = cv2.bilateralFilter(gray, 5, 50, 50)
        edged = cv2.Canny(filtered, lower, upper, L2gradient = USE_L2_GRADIENT)
    else:
        edged = cv2.Canny(gray, 30, 200)

    with frame.get_lock():
        frame.value += 1
        height.value = max(height.value, image.shape[0])
        width.value = max(width.value, image.shape[1])
    print('\r--> Frame %d/%d' % (frame.value, len(os.listdir(FRAME_DIR))), end='')

    return edged[::-1]


def get_trace(data):
    for i in range(len(data)):
        data[i][data[i] > 1] = 1
    bmp = potrace.Bitmap(data)
    path = bmp.trace(2, potrace.TURNPOLICY_MINORITY, 1.0, 1, .5)
    return path


def get_latex(filename):
    latex = []
    path = get_trace(get_contours(filename))

    for curve in path.curves:
        segments = curve.segments
        start = curve.start_point
        for segment in segments:
            x0, y0 = start
            if segment.is_corner:
                x1, y1 = segment.c
                x2, y2 = segment.end_point
                latex.append('((1-t)%f+t%f,(1-t)%f+t%f)' % (x0, x1, y0, y1))
                latex.append('((1-t)%f+t%f,(1-t)%f+t%f)' % (x1, x2, y1, y2))
            else:
                x1, y1 = segment.c1
                x2, y2 = segment.c2
                x3, y3 = segment.end_point
                latex.append('((1-t)((1-t)((1-t)%f+t%f)+t((1-t)%f+t%f))+t((1-t)((1-t)%f+t%f)+t((1-t)%f+t%f)),\
                (1-t)((1-t)((1-t)%f+t%f)+t((1-t)%f+t%f))+t((1-t)((1-t)%f+t%f)+t((1-t)%f+t%f)))' % \
                (x0, x1, x1, x2, x1, x2, x2, x3, y0, y1, y1, y2, y1, y2, y2, y3))
            start = segment.end_point
    return latex


def get_expressions(frame):
    exprid = 0
    exprs = []
    for expr in get_latex(FRAME_DIR + '/frame%d.%s' % (frame+1, FILE_EXT)):
        exprid += 1
        exprs.append({'id': 'expr-' + str(exprid), 'latex': expr, 'color': COLOUR, 'secret': True})
    return exprs


@app.route('/')
def index():
    frame_num = int(request.args.get('frame'))
    frame_files = [f for f in os.listdir(FRAME_DIR) if not f.startswith('.')]
    if frame_num >= len(frame_files):
        return {'result': None}

    # Recompute frame on-the-fly to allow dynamic updates
    return json.dumps({'result': get_expressions(frame_num) })


@app.route("/calculator")
def client():
    frame_files = [f for f in os.listdir(FRAME_DIR) if not f.startswith('.')]
    return render_template('index.html', api_key='dcb31709b452b1cf9dc26972add0fda6', # Development-only API_key. See https://www.desmos.com/api/v1.8/docs/index.html#document-api-keys
            height=height.value, width=width.value, total_frames=len(frame_files), download_images=DOWNLOAD_IMAGES, show_grid=SHOW_GRID, screenshot_size=SCREENSHOT_SIZE, screenshot_format=SCREENSHOT_FORMAT)


@app.route("/upload", methods=['POST'])
def upload():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    # Check file extension
    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'bmp'}
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in allowed_extensions:
        return jsonify({'error': 'Invalid file type. Use PNG, JPG, GIF, or BMP'}), 400

    # Get frame number from request or default to 1
    frame_num = request.form.get('frame', 1, type=int)

    # Save file
    filename = f'frame{frame_num}.{FILE_EXT}'
    filepath = os.path.join(FRAME_DIR, filename)
    file.save(filepath)

    # Update dimensions
    img = cv2.imread(filepath)
    if img is not None:
        height.value = max(height.value, img.shape[0])
        width.value = max(width.value, img.shape[1])

    return jsonify({'success': True, 'filename': filename, 'frame': frame_num})


@app.route("/frames", methods=['GET'])
def list_frames():
    frame_files = sorted([f for f in os.listdir(FRAME_DIR) if not f.startswith('.') and f.startswith('frame')])
    return jsonify({'frames': frame_files, 'total': len(frame_files)})


if __name__ == '__main__':

    try:
        opts, args = getopt.getopt(sys.argv[1:], "hf:e:c:bdlg", ['static', 'block=', 'maxpblock=', 'yes', 'no-browser', 'size=', 'format='])

    except getopt.GetoptError:
        print('Error: Invalid argument(s)\n')
        help()
        sys.exit(2)

    eula = ''

    try:
        for opt, arg in opts:
            if opt == '-h':
                help()
                sys.exit()
            elif opt == '-f':
                FRAME_DIR = arg
            elif opt == '-e':
                FILE_EXT = arg
            elif opt == '-c':
                COLOUR = arg
            elif opt == '-b':
                BILATERAL_FILTER = True
            elif opt == '-d':
                DOWNLOAD_IMAGES = True
            elif opt == '-l':
                USE_L2_GRADIENT = True
            elif opt == '-g':
                SHOW_GRID = False
            elif opt == '--yes':
                eula = 'y'
            elif opt == '--no-browser':
                OPEN_BROWSER = False
            elif opt == '--size':
                SCREENSHOT_SIZE = [ int(n) for n in arg.split('x', maxsplit=1) ]

                if len(SCREENSHOT_SIZE) != 2:
                    raise ValueError
            elif opt == '--format':
                if arg not in ('svg', 'png'):
                    raise ValueError
                SCREENSHOT_FORMAT = arg
                
        frame_latex =  range(len(os.listdir(FRAME_DIR)))

    except (TypeError, ValueError):
        print('Error: Invalid argument(s)\n')
        help()
        sys.exit(2)

    with multiprocessing.Pool(processes = multiprocessing.cpu_count()) as pool:
        print(r'''  _____
 |  __ \
 | |  | | ___  ___ _ __ ___   ___  ___
 | |  | |/ _ \/ __| '_ ` _ \ / _ \/ __|
 | |__| |  __/\__ \ | | | | | (_) \__ \
 |_____/ \___||___/_| |_| |_|\___/|___/
''')
        print('                   BEZIER RENDERER')
        print('Andy 2025')
        print('https://github.com/ChinesePrince07/DesmosBezierRenderer-mac')

        print('''
 = COPYRIGHT =
©Copyright Andy 2025. Based on original work by Junferno. This program is licensed under the GNU General Public License. Desmos Bezier Renderer is in no way, shape, or form endorsed by or associated with Desmos, Inc.

 = EULA =
By using Desmos Bezier Renderer, you agree to comply to the Desmos Terms of Service (https://www.desmos.com/terms). The Software and related documentation are provided "AS IS" and without any warranty of any kind.
''')

        while eula != 'y':
            eula = input('                                      Agree (y/n)? ')
            if eula == 'n':
                quit()

        print('-----------------------------')

        print('Processing %d frames... Please wait for processing to finish before running on frontend\n' % len(os.listdir(FRAME_DIR)))

        start = time()

        try:
            frame_latex = pool.map(get_expressions, frame_latex)
        except cv2.error as e:
            print('[ERROR] Unable to process one or more files. Remember image files should be named <DIRECTORY>/frame<INDEX>.<EXTENSION> where INDEX represents the frame number starting from 1 and DIRECTORY and EXTENSION are defined by command line arguments (e.g. frames/frame1.png). Please check if:\n\tThe files exist\n\tThe files are all valid image files\n\tThe name of the files given is correct as per command line arguments\n\tThe program has the necessary permissions to read the file.\n\nUse backend.py -h for further documentation\n')            

            print('-----------------------------')

            print('Full error traceback:\n')
            traceback.print_exc()
            sys.exit(2)

        print('\r--> Processing complete in %.1f seconds\n' % (time() - start))
        print('\t\t===========================================================================')
        print('\t\t|| GO CHECK OUT YOUR RENDER NOW AT:\t\t\t\t\t ||')
        print('\t\t||\t\t\thttp://127.0.0.1:%d/calculator\t\t ||' % PORT)
        print('\t\t===========================================================================\n')
        print('=== SERVER LOG (Ignore if not dev) ===')

        # with open('cache.json', 'w+') as f:
        #     json.dump(frame_latex, f)

        if OPEN_BROWSER:
            def open_browser():
                webbrowser.open('http://127.0.0.1:%d/calculator' % PORT)
            Timer(1, open_browser).start()

        # Use 0.0.0.0 in production (Railway), 127.0.0.1 locally
        app.run(host='0.0.0.0', port=PORT)
