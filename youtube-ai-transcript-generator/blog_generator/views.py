
import time
from google import genai
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.conf import settings
import json
import yt_dlp
import os
import assemblyai as aai
import httpx
from .models import BlogPost


# Create your views here.
@login_required
def index(request):
    return render(request, 'index.html')

@csrf_exempt
def generate_blog(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            yt_link = data['link']
            user_prompt = data['prompt']

            title = yt_title(yt_link)
            transcription = get_transcription(yt_link)

            if not transcription:
                return JsonResponse({'error': "Failed to get transcript"}, status=500)

            blog_content = generate_blog_from_transcription(transcription, user_prompt)

            if not blog_content:
                return JsonResponse({'error': "Failed to generate blog article"}, status=500)

            new_blog_article = BlogPost.objects.create(
                user=request.user,
                youtube_title=title,
                youtube_link=yt_link,
                generated_content=blog_content,
            )
            new_blog_article.save()

            return JsonResponse({'content': blog_content})

        except Exception as e:
            print("Error in generate_blog:", str(e))  # This prints error in terminal
            return JsonResponse({'error': 'Internal Server Error'}, status=500)

    return JsonResponse({'error': 'Invalid request method'}, status=405)



# def yt_title(link):
#     ydl_opts = {
#         'quiet': True,
#     }
#     with yt_dlp.YoutubeDL(ydl_opts) as ydl:
#         info_dict = ydl.extract_info(link, download=False)
#         return info_dict.get('title', 'No title found')

# def download_audio(link):
#     ydl_opts = {
#         'format': 'bestaudio/best',
#         'outtmpl': os.path.join(settings.MEDIA_ROOT, '%(title)s.%(ext)s'),
#         'cookiefile': os.path.join(settings.BASE_DIR, 'cookies.txt'),
#         'postprocessors': [{
#             'key': 'FFmpegExtractAudio',
#             'preferredcodec': 'mp3',
#             'preferredquality': '192',
#         }],
#     }
#     with yt_dlp.YoutubeDL(ydl_opts) as ydl:
#         info_dict = ydl.extract_info(link, download=True)
#         audio_file = ydl.prepare_filename(info_dict)
#         base, ext = os.path.splitext(audio_file)
#         new_file = base + '.mp3'
#         if os.path.exists(new_file):
#             return new_file
#         else:
#             raise Exception("Failed to download audio")





# Calculate the project root once, as it's common for both functions
# settings.BASE_DIR points to 'MINI_PROJECT/youtube-ai-transcript-generator/ai_blog_app/'
# Moving up one directory gets us to 'MINI_PROJECT/youtube-ai-transcript-generator/'
PROJECT_ROOT = os.path.dirname(settings.BASE_DIR)
COOKIES_FILE_PATH = os.path.join(PROJECT_ROOT, 'config', 'cookies.txt')

# Ensure the cookies file exists before any yt-dlp operation attempts to use it
if not os.path.exists(COOKIES_FILE_PATH):
    # This will raise an error early if the cookies file is missing,
    # preventing silent failures later.
    raise FileNotFoundError(
        f"Cookies file not found at expected path: {COOKIES_FILE_PATH}. "
        "Please ensure 'cookies.txt' is in 'MINI_PROJECT/youtube-ai-transcript-generator/config/'."
    )

def yt_title(link):
    ydl_opts = {
        'quiet': True,
        'cookiefile': COOKIES_FILE_PATH, # Added cookie file for title extraction as well
        'no_warnings': True, # Suppress warnings for cleaner output
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(link, download=False)
            return info_dict.get('title', 'No title found')
    except yt_dlp.DownloadError as e:
        # Catch specific yt-dlp errors, especially bot detection
        print(f"Error fetching title: {e}")
        return "Error: Could not retrieve title."
    except Exception as e:
        print(f"An unexpected error occurred while getting title: {e}")
        return "Error: An unexpected issue occurred."

def download_audio(link):
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(settings.MEDIA_ROOT, '%(id)s.%(ext)s'), # Use %(id)s for unique filenames
        'cookiefile': COOKIES_FILE_PATH, # Use the global cookies file path
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'noplaylist': True,     # Process only a single video, not a playlist
        'nocheckcertificate': True, # Useful in some deployment environments
        'quiet': True,          # Suppress most console output
        'no_warnings': True,    # Suppress warnings
    }

    try:
        # Ensure MEDIA_ROOT directory exists before downloading
        os.makedirs(settings.MEDIA_ROOT, exist_ok=True)

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(link, download=True)
            
            # Use info_dict['id'] to construct the final filename,
            # as it's guaranteed to be unique and consistent.
            video_id = info_dict.get('id')
            if not video_id:
                raise Exception("Could not get video ID from YouTube info.")

            # The postprocessor will convert the downloaded file to .mp3
            # The outtmpl uses %(id)s, so the expected final file name will be <video_id>.mp3
            expected_mp3_path = os.path.join(settings.MEDIA_ROOT, f"{video_id}.mp3")

            if os.path.exists(expected_mp3_path):
                return expected_mp3_path
            else:
                # If the file isn't found after download and post-processing, something went wrong.
                raise Exception(f"Failed to find the expected audio file at {expected_mp3_path} after download and conversion.")
    except yt_dlp.DownloadError as e:
        print(f"yt-dlp Download Error: {e}")
        # This is where the 'Sign in to confirm you're not a bot' error would manifest
        raise Exception(f"Failed to download audio due to: {e}")
    except Exception as e:
        print(f"An unexpected error occurred during audio download: {e}")
        raise Exception(f"An unexpected error occurred during audio download: {e}")



        

def get_transcription(link):
    audio_file = download_audio(link)
    aai.settings.api_key = settings.ASSEMBLYAI_API_KEY

    transcriber = aai.Transcriber()
    retries = 3
    for i in range(retries):
        try:
            transcript = transcriber.transcribe(audio_file)
            return transcript.text
        except httpx.ReadTimeout:
            if i < retries - 1:
                time.sleep(2)  # wait before retrying
                continue
            else:
                raise
    return None



def generate_blog_from_transcription(transcription, user_prompt):

    client = genai.Client(api_key=settings.GOOGLE_API_KEY)
    prompt = f"""
        {user_prompt}
        here is the Transcript:
        {transcription}
    """

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt  # ✅ pass as plain string
    )

    return response.text



def blog_list(request):
    blog_articles = BlogPost.objects.filter(user=request.user)
    return render(request, "all-blogs.html", {'blog_articles': blog_articles})

def blog_details(request, pk):
    blog_article_detail = BlogPost.objects.get(id=pk)
    if request.user == blog_article_detail.user:
        return render(request, 'blog-details.html', {'blog_article_detail': blog_article_detail})
    else:
        return redirect('/')
    
def user_login(request):
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('/')
        else:
            error_message = "Invalid username or password"
            return render(request, 'login.html', {'error_message': error_message})
        
    return render(request, 'login.html')

def user_signup(request):
    if request.method == 'POST':
        username = request.POST['username']
        email = request.POST['email']
        password = request.POST['password']
        repeatPassword = request.POST['repeatPassword']

        if password == repeatPassword:
            try:
                user = User.objects.create_user(username, email, password)
                user.save()
                login(request, user)
                return redirect('/')
            except:
                error_message = 'Error creating account'
                return render(request, 'signup.html', {'error_message':error_message})
        else:
            error_message = 'Password do not match'
            return render(request, 'signup.html', {'error_message':error_message})
        
    return render(request, 'signup.html')

def user_logout(request):
    logout(request)
    return redirect('/')
