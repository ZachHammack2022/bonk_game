"""Contains platform class and methods."""

class platform():
    
    def __init__(self,x1,x2,y1,y2,color,kill) -> None:
        """ Initializes player object with no acceleration, velocity in position

            Args:
            x (double): x_coordinate
            y (double): y_coordinate
        """
        
        self.kill = kill
        self.x1 = x1
        self.x2 = x2
        self.y1 = y1
        self.y2 = y2
        self.color = color
